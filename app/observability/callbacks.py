import contextvars
import time

from langgraph.errors import GraphBubbleUp

from app.observability import audit
from app.resilience import llm_events

_CTX = contextvars.ContextVar("aegisops_audit_ctx", default=None)
_installed = {"done": False}


def _on_llm_event(event):
    """Attributes every LLM attempt to the agent step that is running right now."""
    ctx = _CTX.get()
    if ctx is None:
        return
    tokens_in = int(event.get("input_tokens") or 0)
    tokens_out = int(event.get("output_tokens") or 0)
    ctx["llm_calls"] += 1
    ctx["input_tokens"] += tokens_in
    ctx["output_tokens"] += tokens_out
    outcome = str(event.get("outcome"))
    audit.record_event(
        ctx["run_id"], "llm_call", agent=ctx["agent"], ok=(outcome == "success"),
        summary=str(event.get("model")) + " attempt " + str(event.get("attempt")) + ": " + outcome,
        payload={"attempt": event.get("attempt"), "outcome": outcome, "error": event.get("error")},
        latency_ms=event.get("latency_ms"), model=event.get("model"),
        input_tokens=tokens_in, output_tokens=tokens_out)


def install():
    if not _installed["done"]:
        llm_events.add_listener(_on_llm_event)
        _installed["done"] = True


def _short(value, n):
    text = str(value or "")
    return text if len(text) <= n else text[: n - 3] + "..."


def summarize(agent, update):
    """A short human summary and a small structured payload of what an agent decided."""
    if agent == "triage":
        t = update.get("triage") or {}
        return ("priority " + str(t.get("priority")) + ", category " + str(t.get("category"))
                + ", route " + ",".join(t.get("route") or []),
                {"priority": t.get("priority"), "category": t.get("category"),
                 "affected_service": t.get("affected_service"), "route": t.get("route"),
                 "reasoning": _short(t.get("reasoning"), 300),
                 "redactions": update.get("redaction_counts") or {}})
    if agent == "investigator":
        inv = update.get("investigation") or {}
        return ("confidence " + str(inv.get("confidence")) + ", tools used " + str(inv.get("tool_calls_used"))
                + ": " + _short(inv.get("root_cause"), 200),
                {"root_cause": _short(inv.get("root_cause"), 600), "confidence": inv.get("confidence"),
                 "needs_human": inv.get("needs_human"), "tool_calls_used": inv.get("tool_calls_used"),
                 "evidence_count": len(inv.get("evidence") or [])})
    if agent == "memory":
        m = update.get("memory_context") or {}
        ids = sorted({r.get("doc_id") for r in (m.get("results") or []) if r.get("doc_id")})
        return ("role " + str(m.get("role")) + ", " + str(m.get("searched_docs")) + " docs searched, match "
                + str(m.get("match_quality")) + ", found " + ",".join(ids),
                {"role": m.get("role"), "searched_docs": m.get("searched_docs"),
                 "match_quality": m.get("match_quality"), "doc_ids": ids})
    if agent == "remediation":
        fix = update.get("fix_proposal") or {}
        p = fix.get("proposal") or {}
        failed = [c.get("name") for c in ((fix.get("sandbox") or {}).get("checks") or []) if not c.get("passed")]
        return ("validated " + str(fix.get("validated")) + ", attempts " + str(fix.get("attempts"))
                + ", " + str(p.get("fix_type")) + " on " + str(p.get("target_service")),
                {"validated": fix.get("validated"), "attempts": fix.get("attempts"),
                 "fix_type": p.get("fix_type"), "target_service": p.get("target_service"),
                 "fix_summary": _short(p.get("summary"), 300), "failed_checks": failed,
                 "failure_reason": _short(fix.get("failure_reason"), 300)})
    if agent == "governance":
        gov = update.get("governance") or {}
        risk = update.get("risk") or {}
        return ("decision " + str(gov.get("decision")) + ", risk " + str(risk.get("score"))
                + " (" + str(risk.get("level")) + ")",
                {"decision": gov.get("decision"), "requires_approval": gov.get("requires_approval"),
                 "reason": _short(gov.get("reason"), 400), "risk_score": risk.get("score"),
                 "risk_level": risk.get("level"),
                 "risk_factors": [{"name": f.get("name"), "points": f.get("points")}
                                  for f in (risk.get("factors") or [])],
                 "execution": ((gov.get("execution") or {}).get("message"))})
    return ("completed", {"keys": sorted(update.keys())})


def audited(name, node):
    """Wraps an agent so every run writes its decisions, tool calls and token use to the audit log."""
    install()

    def wrapper(state):
        run_id = state.get("run_id")
        if not run_id:
            return node(state)                       # not an audited run

        ctx = {"run_id": run_id, "agent": name, "llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        token = _CTX.set(ctx)
        started = time.time()
        try:
            update = node(state)
        except GraphBubbleUp:
            latency = int((time.time() - started) * 1000)
            if name == "governance":
                proposal = (state.get("fix_proposal") or {}).get("proposal") or {}
                audit.record_event(
                    run_id, "approval_requested", agent=name, ok=True,
                    summary="paused, waiting for human approval",
                    payload={"priority": (state.get("triage") or {}).get("priority"),
                             "fix_summary": _short(proposal.get("summary"), 300)},
                    latency_ms=latency)
                audit.upsert_incident(run_id, status="awaiting_approval")
            raise                                    # the pause itself must pass through untouched
        except Exception as exc:
            audit.record_event(
                run_id, "agent_step", agent=name, ok=False,
                summary="crashed: " + type(exc).__name__ + ": " + str(exc)[:200],
                payload={"error": type(exc).__name__}, latency_ms=int((time.time() - started) * 1000))
            raise
        finally:
            _CTX.reset(token)

        latency = int((time.time() - started) * 1000)
        update = update or {}
        new_errors = list(update.get("errors") or [])[len(state.get("errors") or []):]
        ok = not any(("crashed" in e) or ("skipped" in e) for e in new_errors)

        if name == "investigator":
            # Tool events are written when the step ends, from the tool trace.
            for t in (update.get("investigation") or {}).get("tool_trace") or []:
                t_ok = bool(t.get("ok"))
                audit.record_event(
                    run_id, "tool_call", agent=name, ok=t_ok,
                    summary=str(t.get("tool")) + (" ok" if t_ok else " failed"),
                    payload={"tool": t.get("tool"), "args": t.get("args")},
                    latency_ms=t.get("latency_ms"))

        approval = (update.get("governance") or {}).get("approval")
        if name == "governance" and approval:
            audit.record_event(
                run_id, "approval", agent=name, ok=(approval.get("decision") == "approve"),
                summary=str(approval.get("decision")) + " by " + str(approval.get("approver")),
                payload={"decision": approval.get("decision"), "approver": approval.get("approver"),
                         "comment": approval.get("comment")})

        summary, payload = summarize(name, update)
        payload.update({"llm_calls": ctx["llm_calls"], "input_tokens": ctx["input_tokens"],
                        "output_tokens": ctx["output_tokens"], "new_errors": new_errors})
        audit.record_event(run_id, "agent_step", agent=name, ok=ok, summary=summary,
                           payload=payload, latency_ms=latency)

        raw = state.get("raw_alert") or {}
        triage = update.get("triage") or state.get("triage") or {}
        audit.upsert_incident(run_id, alert_id=raw.get("alert_id"), environment=raw.get("environment"),
                              user_role=state.get("user_role"), priority=triage.get("priority"),
                              status=update.get("status"))
        return update

    return wrapper