import pytest

from app.rag.hybrid_search import BM25, normalize, search
from app.rag.ingest import load_documents, parse_document
from app.rag.rbac import can_access, filter_chunks, normalize_role
from app.rag.sample_docs import write_sample_docs

QUERY = "payments-api connection pool exhausted refund handler connections not released after deployment"
DBA_QUERY = "emergency terminate idle sessions raise max_connections payments-db pool exhausted rollback not possible"
SECURITY_QUERY = "api key exposed in application logs rotate credentials payments-api"


@pytest.fixture
def chunks(tmp_path):
    write_sample_docs(tmp_path)
    return load_documents(tmp_path)


def ids_for(chunks, role, query=QUERY):
    visible = filter_chunks(chunks, role)
    return {h.chunk.doc_id for h in search(query, visible)}


def test_documents_load_with_metadata(chunks):
    ids = {c.doc_id for c in chunks}
    assert "PM-2026-031" in ids
    assert len(ids) == 7
    assert all(c.allowed_roles for c in chunks)
    assert len([c for c in chunks if c.doc_id == "PM-2026-031"]) == 4


def test_missing_roles_means_nobody_can_read():
    raw = "---\nid: X-1\ntitle: t\n---\n## Body\nsome text here"
    parsed = parse_document(raw)
    assert parsed[0].allowed_roles == []
    assert can_access("sre", parsed[0].allowed_roles) is False


def test_unknown_role_becomes_guest():
    assert normalize_role("admin") == "guest"
    assert normalize_role(None) == "guest"
    assert normalize_role("  SRE ") == "sre"


def test_sre_finds_the_past_incident(chunks):
    assert "PM-2026-031" in ids_for(chunks, "sre")


def test_developer_cannot_see_dba_runbooks(chunks):
    ids = ids_for(chunks, "developer")
    assert "PM-2026-031" in ids
    assert "RB-DB-001" not in ids
    assert "RB-DB-009" not in ids


def test_dba_sees_emergency_runbook_but_sre_does_not(chunks):
    assert "RB-DB-009" in ids_for(chunks, "dba", DBA_QUERY)
    assert "RB-DB-009" not in ids_for(chunks, "sre", DBA_QUERY)


def test_security_document_only_for_security(chunks):
    assert "PM-2026-052" in ids_for(chunks, "security", SECURITY_QUERY)
    assert "PM-2026-052" not in ids_for(chunks, "sre", SECURITY_QUERY)


def test_guest_only_sees_public_documents(chunks):
    assert ids_for(chunks, "guest") <= {"RB-GEN-005"}


def test_restricted_text_never_leaks(chunks):
    visible = filter_chunks(chunks, "developer")
    hits = search(DBA_QUERY, visible)
    assert not any("pg_terminate_backend" in h.chunk.text for h in hits)


def test_unrelated_query_returns_nothing(chunks):
    visible = filter_chunks(chunks, "sre")
    assert search("chocolate cake baking oven recipe", visible) == []


def test_bm25_prefers_the_rare_term():
    docs = [["pool", "leak"], ["pool", "disk"], ["pool", "cpu"]]
    scores = BM25(docs).score(["leak"])
    assert scores[0] > 0
    assert scores[1] == 0 and scores[2] == 0


def test_normalize_drops_stopwords_and_stems():
    assert normalize("The connections were exhausted") == "connection exhaust"