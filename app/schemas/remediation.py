import json
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class FixType(str, Enum):
    ROLLBACK = "rollback"
    CONFIG_CHANGE = "config_change"
    SQL_PATCH = "sql_patch"
    CODE_DIFF = "code_diff"


class FixProposal(BaseModel):
    fix_type: FixType
    target_service: str
    summary: str = Field(max_length=400)
    rationale: str = Field(max_length=800)
    content: Dict[str, Any]
    rollback_plan: str = Field(max_length=600)
    reversible: bool = True
    requires_restart: bool = False
    supporting_docs: List[str] = Field(default_factory=list)

    @field_validator("content", mode="before")
    @classmethod
    def _parse_content(cls, value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                raise ValueError("content must be a JSON object")
        return value


class SandboxCheck(BaseModel):
    name: str
    passed: bool
    detail: str = Field(max_length=500)


class SandboxResult(BaseModel):
    passed: bool
    fix_type: str
    checks: List[SandboxCheck]
    preview: str = ""


class RemediationResult(BaseModel):
    proposal: Optional[FixProposal] = None
    sandbox: Optional[SandboxResult] = None
    attempts: int = 0
    validated: bool = False
    needs_human: bool = False
    failure_reason: str = ""