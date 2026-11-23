import pytest
from pydantic import ValidationError
from app.schemas.alert import TriageResult


def test_bad_priority_rejected():
    with pytest.raises(ValidationError):
        TriageResult(priority="P9", category="db", affected_service="x",
                     reasoning="r", route=[])


def test_valid_triage_accepted():
    t = TriageResult(priority="P1", category="database", affected_service="payments-db",
                     reasoning="Primary DB down", route=["investigator", "memory"])
    assert t.priority.value == "P1"