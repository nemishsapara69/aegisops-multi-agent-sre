import logging
import threading
import uuid

from app.graph import runner
from app.graph.builder import build_graph
from app.observability import audit

log = logging.getLogger("aegisops.service")

MAX_CONCURRENT = 3          # protects the free LLM tier: extra submissions get HTTP 429

_graph = {"app": None}
_graph_lock = threading.Lock()
_active = {"n": 0}
_active_lock = threading.Lock()
_resuming = set()
_resuming_lock = threading.Lock()


class NotPending(Exception):
    pass


class AlreadyResolving(Exception):
    pass


def get_app():
    with _graph_lock:
        if _graph["app"] is None:
            _graph["app"] = build_graph()       # in-memory checkpointer, see the limits below
        return _graph["app"]


def reset():
    """For tests: forget the graph and all counters."""
    with _graph_lock:
        _graph["app"] = None
    with _active_lock:
        _active["n"] = 0
    with _resuming_lock:
        _resuming.clear()


def new_run_id():
    return "inc-" + uuid.uuid4().hex[:12]


def active_count():
    return _active["n"]


def try_acquire_slot():
    with _active_lock:
        if _active["n"] >= MAX_CONCURRENT:
            return False
        _active["n"] += 1
        return True


def release_slot():
    with _active_lock:
        _active["n"] = max(0, _active["n"] - 1)


def run_incident(run_id, alert, role):
    """Runs in the background. Whatever happens, the slot is released and the failure is recorded."""
    try:
        runner.start_incident(get_app(), alert, role, run_id)
    except Exception as exc:
        log.exception("incident %s failed", run_id)
        audit.record_event(run_id, "incident_failed", ok=False,
                           summary=type(exc).__name__ + ": " + str(exc)[:200],
                           payload={"error": type(exc).__name__})
        audit.upsert_incident(run_id, status="failed")
    finally:
        release_slot()


def incident_view(run_id):
    inc = audit.get_incident(run_id)
    if inc is None:
        return None
    app = get_app()
    state = runner.current_state(app, run_id)
    pending = runner.pending_approval(app, run_id)

    triage = state.get("triage") or {}
    inv = state.get("investigation") or {}
    fixd = state.get("fix_proposal") or {}
    proposal = fixd.get("proposal") or {}
    gov = state.get("governance") or {}
    risk = state.get("risk") or {}

    return {
        "run_id": run_id,
        "status": inc["status"],
        "priority": inc["priority"],
        "environment": inc["environment"],
        "created_at": inc["created_at"],
        "updated_at": inc["updated_at"],
        "awaiting_approval": pending is not None,
        # status says awaiting_approval but nothing is pending: the server restarted (see the limits)
        "approval_orphaned": inc["status"] == "awaiting_approval" and pending is None,
        "category": triage.get("category"),
        "root_cause": inv.get("root_cause"),
        "confidence": inv.get("confidence"),
        "fix": ({"validated": bool(fixd.get("validated")), "type": proposal.get("fix_type"),
                 "target": proposal.get("target_service"), "summary": proposal.get("summary")}
                if proposal else None),
        "risk": {"score": risk.get("score"), "level": risk.get("level")} if risk else None,
        "decision": gov.get("decision"),
        "decision_reason": gov.get("reason"),
        "pending_approval": pending or None,
        "error_count": len(state.get("errors") or []),
    }


def pending_incidents(limit=50):
    app = get_app()
    out = []
    for row in audit.list_incidents(limit=limit, status="awaiting_approval"):
        payload = runner.pending_approval(app, row["run_id"])
        if payload is None:
            continue                        # stale row, nothing is really waiting
        out.append({
            "run_id": row["run_id"], "priority": row["priority"], "environment": row["environment"],
            "updated_at": row["updated_at"], "reasons": payload.get("reasons"),
            "risk_score": (payload.get("risk") or {}).get("score"),
            "fix_summary": (payload.get("fix") or {}).get("summary"),
        })
    return out


def submit_decision(run_id, decision, approver, comment):
    app = get_app()
    with _resuming_lock:
        if run_id in _resuming:
            raise AlreadyResolving()
        _resuming.add(run_id)
    try:
        if runner.pending_approval(app, run_id) is None:
            raise NotPending()
        runner.resume_incident(app, run_id,
                               {"decision": decision, "approver": approver, "comment": comment})
    finally:
        with _resuming_lock:
            _resuming.discard(run_id)