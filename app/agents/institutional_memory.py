import re
from typing import Any, Dict

from app.rag.hybrid_search import search
from app.rag.ingest import load_documents
from app.rag.rbac import filter_chunks, normalize_role
from app.schemas.memory import Citation, RetrievedContext

REDACTION_TAG = re.compile(r"\[[A-Z0-9_]+_REDACTED\]")
MAX_QUERY_CHARS = 1000
SNIPPET_CHARS = 600
TOP_K = 5


def build_query(state):
    triage = state.get("triage") or {}
    inv = state.get("investigation") or {}
    parts = [
        triage.get("category", ""),
        triage.get("affected_service", ""),
        inv.get("root_cause", ""),
        inv.get("suggested_fix_area", ""),
        state.get("sanitized_text", ""),
    ]
    text = " ".join(str(p) for p in parts if p)
    text = REDACTION_TAG.sub(" ", text)          # drop [EMAIL_REDACTED] style noise
    return " ".join(text.split())[:MAX_QUERY_CHARS]


def retrieve(query, role, chunks):
    visible = filter_chunks(chunks, role)        # RBAC first, search second
    hits = search(query, visible, top_k=TOP_K)
    results = [
        Citation(
            doc_id=h.chunk.doc_id,
            title=h.chunk.title,
            doc_type=h.chunk.doc_type,
            section=h.chunk.section,
            snippet=h.chunk.text[:SNIPPET_CHARS],
            score=round(h.fused, 4),
            bm25=round(h.bm25, 3),
            similarity=round(h.similarity, 3),
        )
        for h in hits
    ]
    if not hits:
        quality = "none"
    elif hits[0].strong:
        quality = "strong"
    else:
        quality = "weak"
    return RetrievedContext(
        query=query,
        role=role,
        results=results,
        match_quality=quality,
        searched_docs=len({c.doc_id for c in visible}),
    )


def memory_node(state: Dict[str, Any]) -> Dict[str, Any]:
    role = normalize_role(state.get("user_role"))     # missing role means guest
    query = build_query(state)
    errors = []
    try:
        ctx = retrieve(query, role, load_documents())
    except Exception as e:
        errors.append("memory retrieval failed: " + str(e)[:200])
        ctx = RetrievedContext(query=query, role=role, results=[], match_quality="none", searched_docs=0)

    return {
        "memory_context": ctx.model_dump(mode="json"),
        "completed": list(state.get("completed", [])) + ["memory"],
        "iteration_count": state.get("iteration_count", 0) + 1,
        "errors": list(state.get("errors", [])) + errors,
    }