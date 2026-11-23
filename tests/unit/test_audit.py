from sqlalchemy import text

from app.db.session import session_scope
from app.observability import audit, callbacks
from app.resilience import llm_events
from app.resilience.guards import guarded


def add(run, n=3):
    for i in range(n):
        audit.record_event(run, "agent_step", agent="a" + str(i), summary="step " + str(i), payload={"i": i})


def test_events_get_sequence_numbers_in_order():
    add("r1", 3)
    timeline = audit.get_timeline("r1")
    assert [e["seq"] for e in timeline] == [1, 2, 3]
    assert [e["summary"] for e in timeline] == ["step 0", "step 1", "step 2"]


def test_chain_verifies():
    add("r2", 4)
    assert audit.verify_chain("r2") == (True, None)


def test_tampering_is_detected():
    add("r3", 4)
    with session_scope() as s:
        s.execute(text("UPDATE audit_events SET summary = 'edited' WHERE run_id = 'r3' AND seq = 2"))
    ok, bad = audit.verify_chain("r3")
    assert ok is False and bad == 2


def test_deleted_event_is_detected():
    add("r4", 4)
    with session_scope() as s:
        s.execute(text("DELETE FROM audit_events WHERE run_id = 'r4' AND seq = 2"))
    ok, bad = audit.verify_chain("r4")
    assert ok is False


def test_pii_is_scrubbed_from_summary_and_payload():
    audit.record_event("r5", "agent_step", summary="mail rahul@shop.com",
                       payload={"ip": "10.0.0.5", "nested": {"k": "sk-abc123def456ghi789"}})
    e = audit.get_timeline("r5")[0]
    blob = str(e)
    assert "rahul@shop.com" not in blob
    assert "10.0.0.5" not in blob
    assert "sk-abc123def456ghi789" not in blob
    assert "[EMAIL_REDACTED]" in e["summary"]
    assert audit.verify_chain("r5") == (True, None)


def test_audit_failure_is_survivable(monkeypatch):
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(audit, "session_scope", broken)
    before = audit.AUDIT_FAILURES["count"]
    assert audit.record_event("r", "agent_step") is False
    assert audit.upsert_incident("r", status="x") is False
    assert audit.AUDIT_FAILURES["count"] == before + 2


def test_incident_upsert_creates_then_updates():
    audit.upsert_incident("r7", alert_id="a1", priority="P2", status="triaged")
    audit.upsert_incident("r7", status="resolved_auto", priority=None)
    inc = audit.get_incident("r7")
    assert inc["priority"] == "P2"
    assert inc["status"] == "resolved_auto"
    assert inc["alert_id"] == "a1"


def test_usage_counts_llm_calls_only_once():
    audit.record_event("r6", "llm_call", agent="memory", latency_ms=10, model="m",
                       input_tokens=100, output_tokens=20)
    audit.record_event("r6", "llm_call", agent="memory", latency_ms=5, model="m",
                       input_tokens=50, output_tokens=10)
    audit.record_event("r6", "agent_step", agent="memory", latency_ms=40)
    u = audit.usage_summary("r6")
    assert u["total_input_tokens"] == 150 and u["total_output_tokens"] == 30 and u["llm_calls"] == 2
    assert u["by_agent"]["memory"]["latency_ms"] == 40
    assert u["by_agent"]["memory"]["input_tokens"] == 150


def test_llm_events_inside_a_step_are_attributed():
    def node(state):
        llm_events.emit({"ts": 0, "model": "m1", "attempt": 1, "outcome": "success",
                         "latency_ms": 12, "input_tokens": 100, "output_tokens": 20, "error": ""})
        return {"status": "x"}

    callbacks.audited("memory", node)({"run_id": "r-llm", "errors": []})
    u = audit.usage_summary("r-llm")
    assert u["total_input_tokens"] == 100 and u["llm_calls"] == 1
    assert u["by_agent"]["memory"]["output_tokens"] == 20
    step = [e for e in audit.get_timeline("r-llm") if e["event_type"] == "agent_step"][0]
    assert step["payload"]["llm_calls"] == 1


def test_node_without_run_id_is_not_audited():
    wrapped = callbacks.audited("memory", lambda s: {"ok": True})
    assert wrapped({}) == {"ok": True}
    assert audit.list_incidents() == []


def test_crash_is_marked_not_ok():
    def boom(state):
        raise RuntimeError("kaput")

    wrapped = callbacks.audited("investigator", guarded("investigator", boom))
    wrapped({"run_id": "r-crash", "errors": [], "completed": [], "iteration_count": 0})
    step = [e for e in audit.get_timeline("r-crash") if e["event_type"] == "agent_step"][0]
    assert step["ok"] is False


def test_tool_trace_becomes_tool_call_events():
    update = {"investigation": {"tool_trace": [
        {"tool": "query_db", "args": {"sql": "SELECT 1"}, "ok": True, "latency_ms": 3},
        {"tool": "search_logs", "args": {"service": "x"}, "ok": False, "latency_ms": 9}]},
        "status": "investigated"}
    callbacks.audited("investigator", lambda s: update)({"run_id": "r8", "errors": []})
    tools = [e for e in audit.get_timeline("r8") if e["event_type"] == "tool_call"]
    assert [t["summary"] for t in tools] == ["query_db ok", "search_logs failed"]
    assert tools[1]["ok"] is False


def test_unknown_run_has_empty_timeline():
    assert audit.get_timeline("nope") == []
    assert audit.verify_chain("nope") == (True, None)
    assert audit.get_incident("nope") is None