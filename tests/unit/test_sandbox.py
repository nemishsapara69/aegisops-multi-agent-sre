import pytest
from pydantic import ValidationError

from app.schemas.remediation import FixProposal
from app.tools.mock_data import REPO
from app.tools.sandbox import validate_fix

PATH = "services/payments-api/refund_handler.py"

OLD = '''    conn = db_pool.acquire()
    refund = load_refund(conn, refund_request["refund_id"])
    if refund is None:
        raise ValueError("refund not found")
    result = payment_provider.issue_refund(refund)
    save_result(conn, refund, result)
    db_pool.release(conn)
    return result'''

NEW = '''    conn = db_pool.acquire()
    try:
        refund = load_refund(conn, refund_request["refund_id"])
        if refund is None:
            raise ValueError("refund not found")
        result = payment_provider.issue_refund(refund)
        save_result(conn, refund, result)
        return result
    finally:
        db_pool.release(conn)'''


def proposal(fix_type, content, service="payments-api"):
    return FixProposal(fix_type=fix_type, target_service=service, summary="s",
                       rationale="r", content=content, rollback_plan="undo")


def failed(result):
    return [c.name for c in result.checks if not c.passed]


def edit(old=OLD, new=NEW, file=PATH):
    return proposal("code_diff", {"edits": [{"file": file, "old": old, "new": new}]})


# ---- rollback ----
def test_rollback_valid():
    r = validate_fix(proposal("rollback", {"service": "payments-api",
                                           "from_version": "v2.14.0", "to_version": "v2.13.4"}))
    assert r.passed is True


def test_rollback_unknown_target():
    r = validate_fix(proposal("rollback", {"service": "payments-api",
                                           "from_version": "v2.14.0", "to_version": "v9.9.9"}))
    assert r.passed is False and "target_exists" in failed(r)


def test_rollback_from_must_be_latest():
    r = validate_fix(proposal("rollback", {"service": "payments-api",
                                           "from_version": "v2.13.4", "to_version": "v2.14.0"}))
    assert "from_is_latest" in failed(r)
    assert "target_is_older_and_healthy" in failed(r)


def test_rollback_with_no_previous_version():
    r = validate_fix(proposal("rollback", {"service": "orders-api",
                                           "from_version": "v1.8.2", "to_version": "v1.7.0"},
                              service="orders-api"))
    assert "target_exists" in failed(r)


def test_rollback_service_must_match_target():
    r = validate_fix(proposal("rollback", {"service": "payments-api",
                                           "from_version": "v2.14.0", "to_version": "v2.13.4"},
                              service="orders-api"))
    assert "service_matches_target" in failed(r)


# ---- config change ----
def test_config_valid():
    r = validate_fix(proposal("config_change", {"service": "payments-db",
                                                "changes": {"max_connections": 150}}, service="payments-db"))
    assert r.passed is True


def test_config_out_of_range_and_over_double():
    r = validate_fix(proposal("config_change", {"service": "payments-db",
                                                "changes": {"max_connections": 400}}, service="payments-db"))
    assert "range:max_connections" in failed(r)
    assert "max_2x_increase:max_connections" in failed(r)


def test_config_unknown_key():
    r = validate_fix(proposal("config_change", {"service": "payments-db",
                                                "changes": {"shared_buffers": 5}}, service="payments-db"))
    assert "key_exists:shared_buffers" in failed(r)


def test_config_value_must_be_integer():
    r = validate_fix(proposal("config_change", {"service": "payments-db",
                                                "changes": {"max_connections": "lots"}}, service="payments-db"))
    assert "type:max_connections" in failed(r)


def test_config_unknown_service():
    r = validate_fix(proposal("config_change", {"service": "ghost-db", "changes": {"max_connections": 50}},
                              service="ghost-db"))
    assert "service_known" in failed(r)


# ---- SQL patch ----
def test_sql_valid_and_rolled_back():
    r = validate_fix(proposal("sql_patch", {"statements": [
        "UPDATE payment_errors SET error_count = 0 WHERE error_code = 'DB_TIMEOUT'"]}))
    assert r.passed is True
    assert "rolled_back_cleanly" in [c.name for c in r.checks if c.passed]


@pytest.mark.parametrize("bad", [
    "DELETE FROM payment_errors",
    "UPDATE payment_errors SET error_count = 0",
    "DROP TABLE connections",
    "UPDATE connections SET active = 1 WHERE service = 'x'; DROP TABLE connections",
])
def test_sql_unsafe_statements_blocked(bad):
    r = validate_fix(proposal("sql_patch", {"statements": [bad]}))
    assert r.passed is False
    assert any(name.startswith("statement_1") for name in failed(r))


def test_sql_row_limit():
    grow = "INSERT INTO connections SELECT service, minute, active, max_allowed FROM connections"
    r = validate_fix(proposal("sql_patch", {"statements": [grow] * 4}))
    assert "rows_affected_limit" in failed(r)


def test_sql_unknown_table_fails_dry_run():
    r = validate_fix(proposal("sql_patch", {"statements": ["UPDATE nope SET a = 1 WHERE b = 2"]}))
    assert "dry_run_executes" in failed(r)


# ---- code diff ----
def test_code_valid_fix_has_diff_preview():
    r = validate_fix(edit())
    assert r.passed is True
    assert "finally" in r.preview and "+" in r.preview


def test_code_tolerates_trailing_whitespace():
    assert validate_fix(edit(old=OLD.replace("\n", "   \n"))).passed is True


def test_code_old_text_not_found():
    assert "edit_1" in failed(validate_fix(edit(old="this text is not in the file")))


def test_code_old_text_must_be_unique():
    assert "edit_1" in failed(validate_fix(edit(old="conn")))


def test_code_unknown_file():
    assert "edit_1" in failed(validate_fix(edit(file="services/payments-api/other.py")))


def test_code_dangerous_import_blocked():
    bad_new = NEW.replace("    conn = db_pool.acquire()", "    import os\n    conn = db_pool.acquire()", 1)
    assert "no_dangerous_code:" + PATH in failed(validate_fix(edit(new=bad_new)))


def test_code_syntax_error_blocked():
    assert "syntax:" + PATH in failed(validate_fix(edit(new="    conn = (")))


def test_code_does_not_mutate_repository():
    validate_fix(edit())
    assert "finally" not in REPO[PATH]


# ---- schema leniency ----
def test_content_as_json_string_is_accepted():
    p = FixProposal(fix_type="rollback", target_service="x", summary="s", rationale="r",
                    content='{"a": 1}', rollback_plan="undo")
    assert p.content == {"a": 1}


def test_content_invalid_string_rejected():
    with pytest.raises(ValidationError):
        FixProposal(fix_type="rollback", target_service="x", summary="s", rationale="r",
                    content="not json", rollback_plan="undo")