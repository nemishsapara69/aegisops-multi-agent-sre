from dataclasses import dataclass
from pathlib import Path
from typing import List

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FOLDERS = ["runbooks", "postmortems"]


@dataclass
class Chunk:
    doc_id: str
    title: str
    doc_type: str
    services: List[str]
    allowed_roles: List[str]
    section: str
    text: str

    @property
    def search_text(self):
        return " ".join([self.title, self.section, " ".join(self.services), self.text])


def _split_list(value):
    return [v.strip().lower() for v in value.split(",") if v.strip()]


def parse_document(raw, fallback_id="unknown"):
    """Split one markdown document into section chunks that carry its metadata."""
    raw = raw.lstrip("\ufeff")
    meta = {}
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip().lower()] = value.strip()
            body = parts[2]

    doc_id = meta.get("id", fallback_id)
    title = meta.get("title", doc_id)
    doc_type = meta.get("type", "document")
    services = _split_list(meta.get("services", ""))
    allowed = _split_list(meta.get("allowed_roles", ""))   # missing means nobody (default deny)

    sections = []
    current_title = "Summary"
    current_lines = []
    for line in body.splitlines():
        if line.startswith("## "):
            if "".join(current_lines).strip():
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if "".join(current_lines).strip():
        sections.append((current_title, "\n".join(current_lines).strip()))

    return [Chunk(doc_id, title, doc_type, services, allowed, s, t) for s, t in sections]


def load_documents(base_dir=None):
    base = Path(base_dir) if base_dir is not None else DATA_DIR
    chunks = []
    for folder in FOLDERS:
        folder_path = base / folder
        if not folder_path.is_dir():
            continue
        for path in sorted(folder_path.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            chunks.extend(parse_document(raw, fallback_id=path.stem))
    return chunks