from app.rag.hybrid_search import search
from app.rag.ingest import load_documents
from app.rag.rbac import filter_chunks

chunks = load_documents()
print("chunks:", len(chunks), "| documents:", len({c.doc_id for c in chunks}))


def show(query, role):
    visible = filter_chunks(chunks, role)
    hits = search(query, visible)
    print("\nROLE:", role, "| searchable documents:", len({c.chunk_doc for c in []} or {c.doc_id for c in visible}))
    print("QUERY:", query)
    if not hits:
        print("  (no relevant result)")
    for h in hits:
        print("  %-12s %-22s fused=%.4f bm25=%.2f sim=%.2f" % (
            h.chunk.doc_id, h.chunk.section, h.fused, h.bm25, h.similarity))


Q = "payments-api connection pool exhausted refund handler connections not released after deployment"
for role in ["sre", "developer", "guest"]:
    show(Q, role)

DBA_Q = "emergency terminate idle sessions raise max_connections payments-db pool exhausted rollback not possible"
for role in ["dba", "sre"]:
    show(DBA_Q, role)

show("connection pool exhaustion", "sre")        # fuzzy match: 'exhaustion' vs 'exhausted'
show("coffee machine broken in the kitchen", "sre")   # should find nothing