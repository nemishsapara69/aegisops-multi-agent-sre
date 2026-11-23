import pytest

from app.agents import institutional_memory as mem
from app.rag.ingest import load_documents
from app.rag.sample_docs import write_sample_docs

STATE = {
    "triage": {"priority": "P1", "category": "database", "affected_service": "payments-db"},
    "investigation": {
        "root_cause": "A connection leak in the payments-api v2.14.0 deployment refund handler "
                      "did not release connections, exhausting the payments-db connection pool",
        "suggested_fix_area": "payments-api code release connections",
    },
    "sanitized_text": "Payments failing. Contact: [EMAIL_REDACTED] at [IPV4_REDACTED]",
    "user_role": "sre",
}


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    write_sample_docs(tmp_path)
    chunks = load_documents(tmp_path)
    monkeypatch.setattr(mem, "load_documents", lambda *a, **k: chunks)


def run(role=None, state=STATE):
    s = dict(state)
    if role is None:
        s.pop("user_role", None)
    else:
        s["user_role"] = role
    return mem.memory_node(s)


def test_returns_cited_results(seeded):
    out = run("sre")
    ctx = out["memory_context"]
    ids = {r["doc_id"] for r in ctx["results"]}
    assert "PM-2026-031" in ids
    assert all(r["snippet"] for r in ctx["results"])
    assert ctx["match_quality"] in ("strong", "weak")
    assert out["completed"] == ["memory"]
    assert out["iteration_count"] == 1
    assert out["errors"] == []


def test_role_changes_what_is_visible(seeded):
    sre = run("sre")["memory_context"]
    dev = run("developer")["memory_context"]
    assert sre["searched_docs"] == 5
    assert dev["searched_docs"] == 3
    assert "RB-DB-001" not in {r["doc_id"] for r in dev["results"]}


def test_missing_role_means_guest(seeded):
    ctx = run(None)["memory_context"]
    assert ctx["role"] == "guest"
    assert ctx["searched_docs"] == 1


def test_redaction_tags_not_in_query(seeded):
    ctx = run("sre")["memory_context"]
    assert "REDACTED" not in ctx["query"]


def test_retrieval_failure_is_survivable(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(mem, "load_documents", boom)
    out = mem.memory_node(dict(STATE))
    assert len(out["errors"]) == 1
    assert out["memory_context"]["results"] == []
    assert "memory" in out["completed"]


def test_unrelated_incident_gives_no_match(seeded):
    state = {
        "triage": {"category": "facilities", "affected_service": "kitchen"},
        "investigation": {"root_cause": "coffee machine broken in the kitchen"},
        "sanitized_text": "",
        "user_role": "sre",
    }
    ctx = mem.memory_node(state)["memory_context"]
    assert ctx["results"] == []
    assert ctx["match_quality"] == "none"