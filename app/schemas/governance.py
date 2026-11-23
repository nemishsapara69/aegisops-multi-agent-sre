from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class RiskFactor(BaseModel):
    name: str
    points: int
    detail: str = Field(max_length=300)


class RiskAssessment(BaseModel):
    score: int = Field(ge=0, le=100)
    level: str                       # low / medium / high
    factors: List[RiskFactor]


class ApprovalDecision(BaseModel):
    decision: str                    # approve / reject
    approver: str = Field(min_length=1, max_length=100)
    comment: str = Field(default="", max_length=500)

    @field_validator("decision")
    @classmethod
    def _check_decision(cls, value):
        value = str(value).strip().lower()
        if value not in ("approve", "reject"):
            raise ValueError("decision must be 'approve' or 'reject'")
        return value


class ExecutionResult(BaseModel):
    executed: bool
    mode: str                        # always "mock" in this project
    message: str = Field(max_length=500)
    checks_rerun_passed: bool


class GovernanceResult(BaseModel):
    # auto_executed / approved_executed / rejected / escalated / execution_blocked
    decision: str
    requires_approval: bool          # True when a human decision was requested
    reason: str = Field(max_length=700)
    approval: Optional[ApprovalDecision] = None
    execution: Optional[ExecutionResult] = None