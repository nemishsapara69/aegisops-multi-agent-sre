import time

from langgraph.errors import GraphBubbleUp

from app.resilience import limits
from app.schemas.governance import GovernanceResult
from app.schemas.investigation import InvestigationReport
from app.schemas.memory import RetrievedContext
from app.schemas.remediation import RemediationResult


def _investigator_fallback(state, reason):
    report = InvestigationReport(
        root_cause=("Investigation unavailable. " + reason)[:700], confidence=0.0, evidence=[],
        suggested_fix_area="Escalate to a human engineer.", needs_human=True)
    return {"investigation": report.model_dump(mode="json")}


def _memory_fallback(state, reason):
    ctx = RetrievedContext(query="", role=str(state.get("user_role") or "guest"),
                           results=[], match_quality="none", searched_docs=0)
    return {"memory_context": ctx.model_dump(mode="json")}


def _remediation_fallback(state, reason):
    result = RemediationResult(validated=False, needs_human=True,
                               failure_reason=("Remediation unavailable. " + reason)[:500])
    return {"fix_proposal": result.model_dump(mode="json"), "status": "remediation_failed"}


def _governance_fallback(state, reason):
    gov = GovernanceResult(decision="escalated", requires_approval=False,
                           reason=("Escalated to a human. Governance could not run: " + reason)[:700])
    return {"governance": gov.model_dump(mode="json"), "status": "escalated",
            "risk": state.get("risk") or {}}


FALLBACKS = {
    "investigator": _investigator_fallback,
    "memory": _memory_fallback,
    "remediation": _remediation_fallback,
    "governance": _governance_fallback,
}


def _base_update(state, name, error):
    return {
        "completed": list(state.get("completed", [])) + [name],
        "iteration_count": state.get("iteration_count", 0) + 1,
        "errors": list(state.get("errors", [])) + [error],
    }


def _expired(state):
    started = state.get("started_at")
    if not started:
        return False
    return (time.time() - float(started)) > limits.MAX_INCIDENT_SECONDS


def guarded(name, node):
    """Wraps an agent so it can never crash the incident. Nodes without a fallback are returned as is."""
    fallback = FALLBACKS.get(name)
    if fallback is None:
        return node

    def wrapper(state):
        # Governance is exempt: it is fast, has no LLM, and a human may answer hours later.
        if name != "governance" and _expired(state):
            reason = "incident time budget of " + str(limits.MAX_INCIDENT_SECONDS) + "s exceeded"
            update = _base_update(state, name, name + " skipped: " + reason)
            update.update(fallback(state, reason))
            return update
        try:
            return node(state)
        except GraphBubbleUp:
            raise                # human-approval pauses must pass through untouched
        except Exception as exc:
            reason = type(exc).__name__ + ": " + str(exc)[:200]
            update = _base_update(state, name, name + " crashed: " + reason)
            update.update(fallback(state, reason))
            return update

    return wrapper