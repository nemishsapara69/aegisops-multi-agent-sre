import pytest
from langgraph.graph import END

from app.agents import investigator, remediation, triage_router
from app.graph.builder import build_graph, route_next, MAX_STEPS
from app.graph.runner import pending_approval, resume_incident, start_incident
from app.tools.executor import EXECUTION_LOG
from app.observability import audit

class FakeReply:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, text):
        self.text = text

    def invoke(self, messages):
        return FakeReply(self.text)


P1_REPLY = ('{"priority": "P1", "category": "database", "affected_service": "payments-db",'
            ' "reasoning": "Production outage", "route": ["investigator", "memory"]}')

P4_REPLY = ('{"priority": "P4", "category": "application", "affected_service": "docs-site",'
            ' "reasoning": "Cosmetic typo", "route": ["memory"]}')

ALERT = {"alert_id": "a1", "source": "pagerduty", "environment": "production",
         "text": "Payments failing for all users"}

FULL = ["investigator", "memory", "remediation", "governance"]

GOOD_FIX = {
    "fix_type": "rollback",
    "target_service": "payments-api",
    "summary": "Roll back payments-api to v2.13.4",
    "rationale": "v2.14.0 leaks connections",
    "content": {"service": "payments-api", "from_version": "v2.14.0", "to_version": "v2.13.4"},
    "rollback_plan": "Redeploy v2.14.0",
    "reversible": True,
    "requires_restart": False,
    "supporting_docs": ["RB-DB-001"],
}
RISKY_FIX = dict(GOOD_FIX, reversible=False, requires_restart=True)
BAD_FIX = dict(GOOD_FIX, content={"service": "payments-api", "from_version": "v2.14.0", "to_version": "v0.0.1"})

APPROVE = {"decision": "approve", "approver": "asha", "comment": "ok"}
REJECT = {"decision": "reject", "approver": "asha", "comment": "too risky"}


class FakeInvReply:
    content = ""
    tool_calls = [{
        "name": "submit_report",
        "id": "c1",
        "args": {
            "root_cause": "Pool exhausted",
            "confidence": 0.9,
            "evidence": [{"source": "query_db", "detail": "100/100 connections"}],
            "suggested_fix_area": "connection pool",
            "needs_human": False,
        },
    }]

def test_audit_trail_records_each_agent_and_the_approval_pause(monkeypatch):
    run(monkeypatch, P1_REPLY, "audit-pause")
    events = audit.get_timeline("audit-pause")
    steps = [e["agent"] for e in events if e["event_type"] == "agent_step"]
    assert steps == ["triage", "investigator", "memory", "remediation"]
    assert any(e["event_type"] == "approval_requested" for e in events)
    assert audit.get_incident("audit-pause")["status"] == "awaiting_approval"
    assert audit.verify_chain("audit-pause") == (True, None)


def test_audit_trail_after_approval(monkeypatch):
    app, _ = run(monkeypatch, P1_REPLY, "audit-approve")
    resume_incident(app, "audit-approve", APPROVE)
    events = audit.get_timeline("audit-approve")
    assert "approval" in [e["event_type"] for e in events]
    steps = [e["agent"] for e in events if e["event_type"] == "agent_step"]
    assert steps[-1] == "governance"
    inc = audit.get_incident("audit-approve")
    assert inc["priority"] == "P1" and inc["status"] == "resolved_approved"
    assert audit.verify_chain("audit-approve") == (True, None)
    

class FakeInvLLM:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return FakeInvReply()


def make_rem_llm(args):
    class _Reply:
        content = ""
        tool_calls = [{"name": "submit_fix", "id": "r1", "args": args}]

    class _LLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return _Reply()

    return _LLM()


@pytest.fixture(autouse=True)
def clean_execution_log():
    EXECUTION_LOG.clear()
    yield
    EXECUTION_LOG.clear()


def run(monkeypatch, triage_reply, thread, fix=GOOD_FIX):
    monkeypatch.setattr(triage_router, "get_llm", lambda *a, **k: FakeLLM(triage_reply))
    monkeypatch.setattr(investigator, "get_llm", lambda *a, **k: FakeInvLLM())
    monkeypatch.setattr(remediation, "get_llm", lambda *a, **k: make_rem_llm(fix))
    app = build_graph()
    state = start_incident(app, ALERT, "sre", thread)
    return app, state


def test_p1_pauses_and_executes_nothing(monkeypatch):
    app, state = run(monkeypatch, P1_REPLY, "p1-pause")
    assert pending_approval(app, "p1-pause") is not None
    assert state["completed"] == ["investigator", "memory", "remediation"]
    assert EXECUTION_LOG == []


def test_approval_request_contains_what_a_human_needs(monkeypatch):
    app, _ = run(monkeypatch, P1_REPLY, "p1-payload")
    payload = pending_approval(app, "p1-payload")
    assert payload["priority"] == "P1"
    assert payload["fix"]["type"] == "rollback"
    assert payload["risk"]["score"] >= 60
    assert payload["reasons"]


def test_approve_resumes_and_executes(monkeypatch):
    app, _ = run(monkeypatch, P1_REPLY, "p1-approve")
    state = resume_incident(app, "p1-approve", APPROVE)
    assert state["governance"]["decision"] == "approved_executed"
    assert state["status"] == "resolved_approved"
    assert state["completed"] == FULL
    assert len(EXECUTION_LOG) == 1
    assert pending_approval(app, "p1-approve") is None


def test_reject_never_executes(monkeypatch):
    app, _ = run(monkeypatch, P1_REPLY, "p1-reject")
    state = resume_incident(app, "p1-reject", REJECT)
    assert state["governance"]["decision"] == "rejected"
    assert state["status"] == "rejected"
    assert EXECUTION_LOG == []


def test_invalid_approval_is_treated_as_reject(monkeypatch):
    app, _ = run(monkeypatch, P1_REPLY, "p1-invalid")
    state = resume_incident(app, "p1-invalid", {"decision": "maybe", "approver": "asha"})
    assert state["governance"]["decision"] == "rejected"
    assert EXECUTION_LOG == []


def test_low_risk_p4_auto_executes(monkeypatch):
    app, state = run(monkeypatch, P4_REPLY, "p4-auto")
    assert pending_approval(app, "p4-auto") is None
    assert state["governance"]["decision"] == "auto_executed"
    assert state["status"] == "resolved_auto"
    assert state["completed"] == FULL
    assert len(EXECUTION_LOG) == 1


def test_high_risk_p4_still_needs_a_human(monkeypatch):
    app, _ = run(monkeypatch, P4_REPLY, "p4-risky", fix=RISKY_FIX)
    assert pending_approval(app, "p4-risky") is not None
    assert EXECUTION_LOG == []


def test_unvalidated_fix_escalates_without_asking_or_executing(monkeypatch):
    app, state = run(monkeypatch, P1_REPLY, "p1-bad", fix=BAD_FIX)
    assert pending_approval(app, "p1-bad") is None
    assert state["governance"]["decision"] == "escalated"
    assert state["status"] == "escalated"
    assert EXECUTION_LOG == []


def test_loop_protection_stops_graph():
    state = {"triage": {"route": ["investigator"]}, "iteration_count": MAX_STEPS}
    assert route_next(state) == END


def test_route_ends_when_all_done():
    state = {"triage": {"route": ["investigator", "governance"]},
             "completed": ["investigator", "governance"], "iteration_count": 2}
    assert route_next(state) == END