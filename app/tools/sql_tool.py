import json
import re
import sqlite3

from app.tools.mock_data import SEED_SQL

MAX_ROWS = 20
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|vacuum)\b",
    re.I,
)


def _validate(sql):
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned.lower().startswith("select"):
        raise ValueError("Only SELECT queries are allowed")
    if ";" in cleaned:
        raise ValueError("Only one statement is allowed")
    if FORBIDDEN.search(cleaned):
        raise ValueError("Query contains a forbidden keyword")
    return cleaned


def query_db(sql):
    cleaned = _validate(str(sql))
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SEED_SQL)
        conn.execute("PRAGMA query_only = ON")      # second safety layer
        conn.row_factory = sqlite3.Row
        cur = conn.execute(cleaned)
        rows = [dict(r) for r in cur.fetchmany(MAX_ROWS)]
        return json.dumps(rows)
    finally:
        conn.close()