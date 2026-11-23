from app.rag.ingest import DATA_DIR
from app.rag.sample_docs import write_sample_docs

for path in write_sample_docs(DATA_DIR):
    print("wrote", path)