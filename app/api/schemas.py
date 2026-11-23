from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AlertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")      # unknown fields (like user_role) are rejected

    alert_id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=50)
    text: str = Field(min_length=1, max_length=5000)
    environment: str = Field(default="production", min_length=1, max_length=50)


class ApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")      # the approver name comes from the API key only

    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=500)