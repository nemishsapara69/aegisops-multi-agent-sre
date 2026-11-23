from typing import Any, Dict, List, Optional

from langgraph.types import interrupt

from app.schemas.governance import (
    ApprovalDecision, ExecutionResult, GovernanceResult, RiskAssessment, RiskFactor,
)
from app.schemas.remediation import FixProposal
from app.tools.executor import execute_fix

AUTO_PRIORITIES = ("P3", "P4")
AUTO_MAX_SCORE = 60            # a score at or above this always needs a human
LOW_MAX = 35
LOW_CONFIDENCE = 0.7

FIX_BASE = {"config_change": 20, "rollback": 25, "code_diff": 35, "sql_patch": 40}
ENV_POINTS = {"production": 25, "staging": 5, "development": 0, "dev": 0, "test": 0}
UNKNOWN_ENV_POINTS = 25        # unknown environment is treated like production
PRIORITY_POINTS = {"P1": 20, "P2": 15, "P3": 5, "P4": 0}
UNKNOWN_PRIORITY_POINTS = 20


def _level(score):
    if score < LOW_MAX:
        return "low"
    if score < AUTO_MAX_SCORE:
        return "medium"
    return "high"


def score_risk(state: Dict[str, Any], proposal: FixProposal) -> RiskAssessment:
    priority = str((state.get("triage") or {}).get("priority", "P1"))
    env = str((state.get("raw_alert") or {}).get("environment", "production")).strip().lower()
    inv = state.get("investigation") or {}
    try:
        confidence = float(inv.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0

    factors = [
        RiskFactor(name="fix_type", points=FIX_BASE.get(proposal.fix_type.value, 40),
                   detail="fix type " + proposal.fix_type.value),
        RiskFactor(name="environment", points=ENV_POINTS.get(env, UNKNOWN_ENV_POINTS),
                   detail="environment " + env),
        RiskFactor(name="priority", points=PRIORITY_POINTS.get(priority, UNKNOWN_PRIORITY_POINTS),
                   detail="priority " + priority),
    ]
    if not proposal.reversible:
        factors.append(RiskFactor(name="not_reversible", points=20, detail="fix cannot be undone easily"))
    if proposal.requires_restart:
        factors.append(RiskFactor(name="requires_restart", points=10, detail="fix needs a restart"))
    if confidence < LOW_CONFIDENCE:
        factors.append(RiskFactor(name="low_confidence", points=15,
                                  detail="investigation confidence " + str(confidence)))
    if not proposal.supporting_docs:
        factors.append(RiskFactor(name="no_precedent", points=5,
                                  detail="no runbook or past incident supports this fix"))

    total = min(100, sum(f.points for f in factors))
    return RiskAssessment(score=total, level=_level(total), factors=factors)


def needs_human(priority: str, score: int) -> List[str]:
    """Pure policy. An empty list means the system may act alone."""
    reasons = []
    if priority not in AUTO_PRIORITIES:
        reasons.append("Priority " + priority + " changes always need human approval.")
    if score >= AUTO_MAX_SCORE:
        reasons.append("Risk score " + str(score) + " is at or above the auto-execute limit of "
                       + str(AUTO_MAX_SCORE) + ".")
    return reasons


def parse_decision(raw: Any) -> Optional[ApprovalDecision]:
    """Anything that is not a clean approval object returns None, and None is treated as a reject."""
    if not isinstance(raw, dict):
        return None
    try:
        return ApprovalDecision(**raw)
    except Exception:
        return None


def _finish(state, gov, risk, status, errors):
    return {
        "risk": risk.model_dump(mode="json") if risk else {},
        "governance": gov.model_dump(mode="json"),
        "status": status,
        "completed": list(state.get("completed", [])) + ["governance"],
        "iteration_count": state.get("iteration_count", 0) + 1,
        "errors": list(state.get("errors", [])) + errors,
    }


def _execute(proposal, requires_approval, approval, reason, ok_decision, ok_status):
    execution = execute_fix(proposal)
    if execution.executed:
        gov = GovernanceResult(decision=ok_decision, requires_approval=requires_approval,
                               reason=reason, approval=approval, execution=execution)
        return gov, ok_status
    gov = GovernanceResult(decision="execution_blocked", requires_approval=requires_approval,
                           reason="Fix was not applied. " + execution.message, approval=approval,
                           execution=execution)
    return gov, "escalated"


def governance_node(state: Dict[str, Any]) -> Dict[str, Any]:
    # NOTE: interrupt() re-runs this function from the top when the human answers,
    # so everything before interrupt() must be pure (no side effects).
    errors = []
    fix = state.get("fix_proposal") or {}
    proposal_dict = fix.get("proposal")
    priority = str((state.get("triage") or {}).get("priority", "P1"))

    proposal = None
    risk = None
    if proposal_dict:
        try:
            proposal = FixProposal(**proposal_dict)
            risk = score_risk(state, proposal)
        except Exception as e:
            errors.append("governance could not read the fix proposal: " + str(e)[:200])
            proposal = None

    # Rule 1: nothing validated means nothing executes
    if proposal is None or not fix.get("validated"):
        reason = fix.get("failure_reason") or "No validated fix is available."
        gov = GovernanceResult(decision="escalated", requires_approval=False,
                               reason="Escalated to a human. " + reason)
        return _finish(state, gov, risk, "escalated", errors)

    reasons = needs_human(priority, risk.score)

    # Rule 2: low-risk P3/P4 may run on their own
    if not reasons:
        gov, status = _execute(
            proposal, False, None,
            "Auto-executed: priority " + priority + " with " + risk.level + " risk (score "
            + str(risk.score) + ").",
            "auto_executed", "resolved_auto")
        return _finish(state, gov, risk, status, errors)

    # Rule 3: a human decides. The graph pauses here until someone resumes it.
    payload = {
        "question": "Approve this change?",
        "priority": priority,
        "reasons": reasons,
        "risk": risk.model_dump(mode="json"),
        "root_cause": (state.get("investigation") or {}).get("root_cause", ""),
        "fix": {
            "type": proposal.fix_type.value,
            "target": proposal.target_service,
            "summary": proposal.summary,
            "content": proposal.content,
            "rollback_plan": proposal.rollback_plan,
            "reversible": proposal.reversible,
            "requires_restart": proposal.requires_restart,
        },
        "sandbox_preview": (fix.get("sandbox") or {}).get("preview", ""),
    }
    raw = interrupt(payload)
    approval = parse_decision(raw)

    if approval is None:
        gov = GovernanceResult(decision="rejected", requires_approval=True,
                               reason="Approval response was missing or invalid, treated as a reject.")
        return _finish(state, gov, risk, "rejected", errors)
    if approval.decision == "reject":
        gov = GovernanceResult(decision="rejected", requires_approval=True, approval=approval,
                               reason="Rejected by " + approval.approver + ".")
        return _finish(state, gov, risk, "rejected", errors)

    gov, status = _execute(
        proposal, True, approval,
        "Approved by " + approval.approver + " and executed.",
        "approved_executed", "resolved_approved")
    return _finish(state, gov, risk, status, errors)