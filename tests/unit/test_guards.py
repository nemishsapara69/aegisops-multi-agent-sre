import time

import pytest
from langgraph.errors import GraphBubbleUp

from app.agents import triage_router
from app.graph.builder import REAL_NODES, build_graph
from app.graph.runner import pending_approval, start_incident
from app.resilience import guards
from app.tools.executor import EXECUTION_LOG

FULL = ["investigator", "memory", "remediation", "governance"]

P1_REPLY = ('{"priority": "P1", "category": "database", "affected_service": "payments-db",'
            ' "reasoning": "Production outage", "route": ["investigator", "memory"]}')

ALERT = {"alert_id": "a1", "source": "pagerduty", "environment": "production",
         "text": "Payments failing for all users"}


class FakeReply:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, text):
        self.text = text

    def invoke(self, messages):
        return FakeReply(self.text)


def boom(state):
    raise RuntimeError("kaput")


@pytest.fixture(autouse=True)
def clean_execution_log():
    EXECUTION_LOG.clear()
    yield
    EXECUTION_LOG.clear()


def test_investigator_crash_becomes_safe_fallback():
    out = guards.guarded("investigator", boom)({"completed": ["x"], "errors": [], "iteration_count": 3})
    assert out["completed"] == ["x", "investigator"]
    assert out["iteration_count"] == 4
    assert "investigator crashed" in out["errors"][0]
    assert out["investigation"]["needs_human"] is True
    assert out["investigation"]["confidence"] == 0.0


def test_memory_crash_gives_empty_context():
    out = guards.guarded("memory", boom)({})
    assert out["memory_context"]["results"] == []
    assert out["memory_context"]["match_quality"] == "none"


def test_remediation_crash_escalates():
    out = guards.guarded("remediation", boom)({})
    assert out["fix_proposal"]["validated"] is False
    assert out["fix_proposal"]["needs_human"] is True


def test_governance_crash_escalates_and_executes_nothing():
    out = guards.guarded("governance", boom)({})
    assert out["governance"]["decision"] == "escalated"
    assert out["status"] == "escalated"
    assert EXECUTION_LOG == []


def test_pause_signal_passes_through():
    def pause(state):
        raise GraphBubbleUp("pause for approval")

    with pytest.raises(GraphBubbleUp):
        guards.guarded("governance", pause)({})


def test_successful_node_is_untouched():
    assert guards.guarded("memory", lambda s: {"ok": True})({}) == {"ok": True}


def test_expired_budget_skips_the_node():
    called = []

    def node(state):
        called.append(1)
        return {}

    out = guards.guarded("investigator", node)({"started_at": 1.0})
    assert called == []
    assert "skipped" in out["errors"][0]
    assert out["completed"] == ["investigator"]
    assert out["investigation"]["needs_human"] is True


def test_governance_ignores_the_time_budget():
    out = guards.guarded("governance", lambda s: {"ok": True})({"started_at": 1.0})
    assert out == {"ok": True}


def test_no_start_time_means_no_deadline():
    assert guards.guarded("memory", lambda s: {"ok": True})({}) == {"ok": True}


def test_nodes_without_fallback_are_not_wrapped():
    def fn(state):
        return {}

    assert guards.guarded("triage", fn) is fn


def test_crashing_agent_does_not_kill_the_incident(monkeypatch):
    monkeypatch.setattr(triage_router, "get_llm", lambda *a, **k: FakeLLM(P1_REPLY))
    monkeypatch.setitem(REAL_NODES, "investigator", boom)
    app = build_graph()
    state = start_incident(app, ALERT, "sre", "crash-1")
    assert state["completed"] == FULL
    assert state["governance"]["decision"] == "escalated"
    assert pending_approval(app, "crash-1") is None
    assert EXECUTION_LOG == []
    assert any("investigator crashed" in e for e in state["errors"])