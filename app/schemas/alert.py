from enum import Enum
from typing import List
from pydantic import BaseModel, Field


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class RawAlert(BaseModel):
    alert_id: str
    source: str                       # e.g. "prometheus", "pagerduty", "user_ticket"
    text: str
    environment: str = "production"


class TriageResult(BaseModel):
    priority: Priority
    category: str                     # e.g. "database", "network", "deployment"
    affected_service: str
    reasoning: str = Field(max_length=500)
    route: List[str]                  # which agents to call next