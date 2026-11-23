import time

import pytest
from fastapi.testclient import TestClient

from app.agents import investigator, remediation, triage_router
from app.api import service
from app.api.main import app
from app.graph import runner
from app.observability import audit
from app.tools.executor import EXECUTION_LOG

KEYS = "asha-secret:asha:sre:approver,ravi-secret:ravi:developer:member"
ASHA = {"X-API-Key": "asha-secret"}
RAVI = {"X-API-Key": "ravi-secret"}
DONE = ("resolved_auto", "resolved_approved", "rejected", "escalated", "failed")

P1_REPLY = ('{"priority": "P1", "category": "database", "affected_service": "payments-db",'
            ' "reasoning": "Production outage", "route": ["investigator", "memory"]}')

ALERT = {"alert_id": "a1", "source": "pagerduty", "environment": "production",
         "text": "Payments failing for all users"}

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


class FakeReply:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, text):
        self.text = text

    def invoke(self, messages):
        return FakeReply(self.text)


class FakeInvReply:
    content = ""
    tool_calls = [{"name": "submit_report", "id": "c1", "args": {
        "root_cause": "Pool exhausted", "confidence": 0.9,
        "evidence": [{"source": "query_db", "detail": "100/100 connections"}],
        "suggested_fix_area": "connection pool", "needs_human": False}}]


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


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AEGIS_API_KEYS", KEYS)
    monkeypatch.setattr(triage_router, "get_llm", lambda *a, **k: FakeLLM(P1_REPLY))
    monkeypatch.setattr(investigator, "get_llm", lambda *a, **k: FakeInvLLM())
    monkeypatch.setattr(remediation, "get_llm", lambda *a, **k: make_rem_llm(GOOD_FIX))
    service.reset()
    EXECUTION_LOG.clear()
    with TestClient(app) as c:
        yield c
    service.reset()
    EXECUTION_LOG.clear()


def submit(client, headers=RAVI, **overrides):
    body = dict(ALERT)
    body.update(overrides)
    r = client.post("/alerts", json=body, headers=headers)
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


def wait_for(client, run_id, headers=RAVI):
    view = None
    for _ in range(100):
        view = client.get("/incidents/" + run_id, headers=headers).json()
        if view.get("awaiting_approval") or view.get("status") in DONE:
            return view
        time.sleep(0.05)
    return view


def approve(client, run_id, headers=ASHA, decision="approve"):
    return client.post("/approvals/" + run_id, json={"decision": decision, "comment": "ok"}, headers=headers)


def test_health_is_open(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["database"] is True


def test_missing_key_is_401(client):
    assert client.get("/incidents").status_code == 401
    assert client.post("/alerts", json=ALERT).status_code == 401


def test_wrong_key_is_401(client):
    assert client.get("/incidents", headers={"X-API-Key": "nope"}).status_code == 401


def test_no_keys_configured_is_503(client, monkeypatch):
    monkeypatch.delenv("AEGIS_API_KEYS", raising=False)
    assert client.get("/incidents", headers=ASHA).status_code == 503


def test_submit_runs_and_pauses_for_approval(client):
    run_id = submit(client)
    view = wait_for(client, run_id)
    assert view["awaiting_approval"] is True
    assert view["priority"] == "P1"
    assert view["pending_approval"]["fix"]["type"] == "rollback"
    assert view["decision"] is None
    assert EXECUTION_LOG == []


def test_member_cannot_approve(client):
    run_id = submit(client)
    wait_for(client, run_id)
    assert approve(client, run_id, headers=RAVI).status_code == 403
    assert EXECUTION_LOG == []
    assert wait_for(client, run_id)["awaiting_approval"] is True


def test_approver_approves_and_identity_comes_from_the_key(client):
    run_id = submit(client)
    wait_for(client, run_id)
    r = approve(client, run_id)
    assert r.status_code == 200
    assert r.json()["decision"] == "approved_executed"
    assert len(EXECUTION_LOG) == 1
    events = [e for e in audit.get_timeline(run_id) if e["event_type"] == "approval"]
    assert events[0]["payload"]["approver"] == "asha"


def test_second_approval_is_a_conflict(client):
    run_id = submit(client)
    wait_for(client, run_id)
    assert approve(client, run_id).status_code == 200
    assert approve(client, run_id).status_code == 409
    assert len(EXECUTION_LOG) == 1


def test_reject_never_executes(client):
    run_id = submit(client)
    wait_for(client, run_id)
    r = approve(client, run_id, decision="reject")
    assert r.status_code == 200 and r.json()["decision"] == "rejected"
    assert EXECUTION_LOG == []


def test_unknown_incident_is_404(client):
    assert client.get("/incidents/nope", headers=RAVI).status_code == 404
    assert client.get("/incidents/nope/audit", headers=RAVI).status_code == 404
    assert approve(client, "nope").status_code == 404


def test_invalid_decision_is_422(client):
    run_id = submit(client)
    wait_for(client, run_id)
    r = client.post("/approvals/" + run_id, json={"decision": "maybe"}, headers=ASHA)
    assert r.status_code == 422
    assert EXECUTION_LOG == []


def test_identity_fields_in_bodies_are_rejected(client):
    r = client.post("/alerts", json=dict(ALERT, user_role="dba"), headers=RAVI)
    assert r.status_code == 422
    run_id = submit(client)
    wait_for(client, run_id)
    r = client.post("/approvals/" + run_id, json={"decision": "approve", "approver": "boss"}, headers=ASHA)
    assert r.status_code == 422
    assert EXECUTION_LOG == []


def test_pending_list_is_for_approvers(client):
    run_id = submit(client)
    wait_for(client, run_id)
    assert client.get("/approvals/pending", headers=RAVI).status_code == 403
    ids = [p["run_id"] for p in client.get("/approvals/pending", headers=ASHA).json()]
    assert run_id in ids
    approve(client, run_id)
    ids = [p["run_id"] for p in client.get("/approvals/pending", headers=ASHA).json()]
    assert run_id not in ids


def test_memory_role_comes_from_the_api_key(client):
    dev_run = submit(client, headers=RAVI)
    sre_run = submit(client, headers=ASHA)
    wait_for(client, dev_run)
    wait_for(client, sre_run)

    def memory_summary(run_id):
        steps = [e for e in audit.get_timeline(run_id)
                 if e["event_type"] == "agent_step" and e["agent"] == "memory"]
        return steps[0]["summary"]

    assert "role developer" in memory_summary(dev_run)
    assert "role sre" in memory_summary(sre_run)


def test_audit_endpoint(client):
    run_id = submit(client)
    wait_for(client, run_id)
    approve(client, run_id)
    r = client.get("/incidents/" + run_id + "/audit", headers=RAVI)
    assert r.status_code == 200
    body = r.json()
    assert body["chain_intact"] is True
    types = [e["event_type"] for e in body["events"]]
    assert types[0] == "alert_received" and "approval" in types
    assert "total_input_tokens" in body["usage"]


def test_concurrency_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(service, "MAX_CONCURRENT", 0)
    r = client.post("/alerts", json=ALERT, headers=RAVI)
    assert r.status_code == 429
    assert "retry-after" in r.headers


def test_background_crash_marks_the_incident_failed(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(runner, "start_incident", boom)
    run_id = submit(client)
    view = wait_for(client, run_id)
    assert view["status"] == "failed"
    assert service.active_count() == 0