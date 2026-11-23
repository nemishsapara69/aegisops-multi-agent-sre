AGENTS = ["triage", "investigator", "memory", "remediation", "governance"]
DONE_STATUSES = ("resolved_auto", "resolved_approved", "rejected", "escalated", "failed")
ICONS = {"waiting": "⚪", "running": "🔄", "done": "✅", "failed": "❌", "paused": "⏸️"}
LABELS = {"waiting": "waiting", "running": "working", "done": "done", "failed": "failed",
          "paused": "waiting for a human"}


def agent_status(events, finished=False):
    """State of each agent box, worked out from the audit events."""
    state = {a: "waiting" for a in AGENTS}
    paused = False
    for e in events:
        kind, agent = e.get("event_type"), e.get("agent")
        if kind == "agent_step" and agent in state:
            state[agent] = "done" if e.get("ok") else "failed"
        elif kind == "approval_requested":
            paused = True
    if paused and state["governance"] == "waiting":
        state["governance"] = "paused"
    elif not finished and not paused:
        for a in AGENTS:
            if state[a] == "waiting":
                state[a] = "running"
                break
    return state


def summary_from_events(events):
    out = {"priority": None, "category": None, "root_cause": None, "confidence": None,
           "memory_docs": [], "fix_summary": None, "fix_type": None, "fix_validated": None,
           "risk_score": None, "risk_level": None, "risk_factors": [], "decision": None,
           "approver": None}
    for e in events:
        p = e.get("payload") or {}
        if e.get("event_type") == "approval":
            out["approver"] = p.get("approver")
        if e.get("event_type") != "agent_step":
            continue
        agent = e.get("agent")
        if agent == "triage":
            out["priority"], out["category"] = p.get("priority"), p.get("category")
        elif agent == "investigator":
            out["root_cause"], out["confidence"] = p.get("root_cause"), p.get("confidence")
        elif agent == "memory":
            out["memory_docs"] = p.get("doc_ids") or []
        elif agent == "remediation":
            out["fix_summary"], out["fix_type"] = p.get("fix_summary"), p.get("fix_type")
            out["fix_validated"] = p.get("validated")
        elif agent == "governance":
            out["decision"] = p.get("decision")
            out["risk_score"], out["risk_level"] = p.get("risk_score"), p.get("risk_level")
            out["risk_factors"] = p.get("risk_factors") or []
    return out


def latency_by_agent(events):
    result = {}
    for e in events:
        if e.get("event_type") == "agent_step":
            agent = e.get("agent") or "-"
            result[agent] = result.get(agent, 0) + int(e.get("latency_ms") or 0)
    return result


def tokens_by_agent(usage):
    result = {}
    for agent, slot in ((usage or {}).get("by_agent") or {}).items():
        tin, tout = int(slot.get("input_tokens") or 0), int(slot.get("output_tokens") or 0)
        if tin or tout:
            result[agent] = {"input": tin, "output": tout}
    return result


def step_rows(events):
    rows = []
    for e in events:
        rows.append({
            "#": e.get("seq"),
            "type": e.get("event_type"),
            "agent": e.get("agent") or "-",
            "ok": "ok" if e.get("ok") else "FAIL",
            "ms": e.get("latency_ms"),
            "tokens in/out": str(e.get("input_tokens") or 0) + "/" + str(e.get("output_tokens") or 0),
            "summary": e.get("summary"),
        })
    return rows