from typing import Any, Dict, List

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: str                                   # tool that produced it
    detail: str = Field(max_length=600)


class InvestigationReport(BaseModel):
    root_cause: str = Field(max_length=700)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[Evidence]
    suggested_fix_area: str = Field(max_length=500)
    needs_human: bool = False
    tool_calls_used: int = 0
    tool_trace: List[Dict[str, Any]] = Field(default_factory=list)   # used by the audit log later