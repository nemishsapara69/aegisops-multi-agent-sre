import pytest

from app.agents.governance_gate import needs_human, parse_decision, score_risk
from app.schemas.remediation import FixProposal
from app.tools.executor import EXECUTION_LOG, execute_fix

BASE_STATE = {
    "triage": {"priority": "P4"},
    "raw_alert": {"environment": "production"},
    "investigation": {"confidence": 0.9},
}


def fix(fix_type="rollback", content=None, **kw):
    content = content or {"service": "payments-api", "from_version": "v2.14.0", "to_version": "v2.13.4"}
    data = dict(fix_type=fix_type, target_service="payments-api", summary="s", rationale="r",
                content=content, rollback_plan="undo", supporting_docs=["RB-DB-001"])
    data.update(kw)
    return FixProposal(**data)


def state(**overrides):
    s = {k: dict(v) for k, v in BASE_STATE.items()}
    for key, value in overrides.items():
        s[key] = value
    return s


@pytest.fixture(autouse=True)
def clean_log():
    EXECUTION_LOG.clear()
    yield
    EXECUTION_LOG.clear()


# ---- risk score ----
def test_p4_production_rollback_is_medium():
    r = score_risk(state(), fix())
    assert r.score == 50 and r.level == "medium"


def test_dev_config_change_is_low():
    r = score_risk(state(raw_alert={"environment": "dev"}),
                   fix("config_change", {"service": "payments-db", "changes": {"max_connections": 150}}))
    assert r.score == 20 and r.level == "low"


def test_unknown_environment_is_treated_as_production():
    r = score_risk(state(raw_alert={"environment": "moon"}), fix())
    assert r.score == 50


def test_irreversible_restart_adds_points():
    r = score_risk(state(), fix(reversible=False, requires_restart=True))
    assert r.score == 80 and r.level == "high"
    assert {"not_reversible", "requires_restart"} <= {f.name for f in r.factors}


def test_low_confidence_and_no_precedent_add_points():
    r = score_risk(state(investigation={"confidence": 0.5}), fix(supporting_docs=[]))
    assert r.score == 50 + 15 + 5


def test_missing_investigation_counts_as_low_confidence():
    s = state()
    s.pop("investigation")
    assert score_risk(s, fix()).score == 65


def test_score_is_capped_at_100():
    s = state(triage={"priority": "P1"}, investigation={"confidence": 0.1})
    r = score_risk(s, fix("sql_patch", {"statements": ["x"]}, reversible=False,
                          requires_restart=True, supporting_docs=[]))
    assert r.score == 100


# ---- policy ----
def test_p1_and_p2_always_need_a_human():
    assert needs_human("P1", 0)
    assert needs_human("P2", 0)


def test_p3_p4_below_limit_run_alone():
    assert needs_human("P4", 50) == []
    assert needs_human("P3", 59) == []


def test_high_score_needs_a_human_even_for_p4():
    assert needs_human("P4", 60)


def test_unknown_priority_needs_a_human():
    assert needs_human("PX", 0)


# ---- approval parsing ----
def test_valid_approval_parses_and_normalizes():
    d = parse_decision({"decision": " APPROVE ", "approver": "asha"})
    assert d.decision == "approve" and d.approver == "asha"


@pytest.mark.parametrize("raw", [
    "yes",
    None,
    {"decision": "maybe", "approver": "asha"},
    {"decision": "approve", "approver": ""},
    {"decision": "approve"},
])
def test_bad_approval_returns_none(raw):
    assert parse_decision(raw) is None


# ---- executor ----
def test_executor_applies_valid_fix_and_logs_it():
    result = execute_fix(fix())
    assert result.executed is True and result.mode == "mock"
    assert len(EXECUTION_LOG) == 1


def test_executor_blocks_a_fix_that_fails_recheck():
    bad = fix(content={"service": "payments-api", "from_version": "v2.14.0", "to_version": "v9.9.9"})
    result = execute_fix(bad)
    assert result.executed is False and result.checks_rerun_passed is False
    assert EXECUTION_LOG == []