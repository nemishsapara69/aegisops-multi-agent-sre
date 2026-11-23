from typing import List

from pydantic import BaseModel, Field


class Citation(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    section: str
    snippet: str = Field(max_length=700)
    score: float            # fused (RRF) score
    bm25: float             # keyword score
    similarity: float       # fuzzy similarity, 0 to 1


class RetrievedContext(BaseModel):
    query: str
    role: str
    results: List[Citation]
    match_quality: str      # strong / weak / none
    searched_docs: int      # how many documents this role was allowed to search