import pytest

from app.tools.sql_tool import query_db
from app.tools.metrics_tool import get_metrics
from app.tools.logs_tool import search_logs


def test_select_works():
    out = query_db("SELECT service, active FROM connections WHERE minute = '03:10'")
    assert "payments-db" in out


@pytest.mark.parametrize("bad", [
    "DROP TABLE connections",
    "DELETE FROM connections",
    "UPDATE connections SET active = 0",
    "SELECT 1; DROP TABLE connections",
    "PRAGMA table_info(connections)",
])
def test_unsafe_sql_is_blocked(bad):
    with pytest.raises(ValueError):
        query_db(bad)


def test_metrics_returns_data():
    assert "100" in get_metrics("payments-db", "connections_active")


def test_metrics_unknown_service():
    with pytest.raises(ValueError):
        get_metrics("nope", "cpu_percent")


def test_logs_keyword_filter():
    out = search_logs("payments-api", "pool exhausted")
    assert "pool exhausted" in out.lower()


def test_logs_no_match():
    assert search_logs("orders-api", "zzzz") == "No matching log lines."