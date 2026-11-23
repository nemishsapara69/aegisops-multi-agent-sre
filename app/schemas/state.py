from typing import TypedDict, List


class IncidentState(TypedDict, total=False):
    run_id: str
    raw_alert: dict
    sanitized_text: str
    redaction_counts: dict
    completed: List[str]
    triage: dict
    investigation: dict
    memory_context: dict
    fix_proposal: dict
    risk: dict
    governance: dict
    status: str          # triaged / investigating / awaiting_approval / resolved / escalated
    user_role: str       # used later for RBAC
    iteration_count: int
    started_at: float
    retry_count: int
    errors: List[str]