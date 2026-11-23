import ast
import difflib
import re
import sqlite3

from app.schemas.remediation import FixProposal, SandboxCheck, SandboxResult
from app.security.pii_redactor import redact
from app.tools.mock_data import CONFIG_RULES, CURRENT_CONFIG, REPO, SEED_SQL

MAX_ROWS_AFFECTED = 50
MAX_STATEMENTS = 5
MAX_EDITS = 3
MAX_CHANGED_LINES = 60
DOUBLE_LIMIT_KEYS = ("max_connections", "pool_size")
TABLES = ("connections", "deployments", "payment_errors")
FORBIDDEN_SQL = re.compile(r"\b(drop|alter|attach|detach|pragma|vacuum|truncate)\b", re.I)
ALLOWED_SQL_START = ("update", "insert", "delete", "create index")
BANNED_CALLS = {"eval", "exec", "compile", "open", "__import__", "input"}
BANNED_MODULES = {"os", "subprocess", "socket", "shutil", "sys", "ctypes", "pickle"}


def _check(name, passed, detail):
    return SandboxCheck(name=name, passed=bool(passed), detail=str(detail)[:500])


def _norm(text):
    lines = str(text).replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def _seeded_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SEED_SQL)
    return conn


def deployment_history():
    conn = _seeded_db()
    try:
        return conn.execute(
            "SELECT service, version, deployed_at, status FROM deployments "
            "ORDER BY service, deployed_at DESC"
        ).fetchall()
    finally:
        conn.close()


def _same_service(p, service):
    return _check(
        "service_matches_target",
        service == p.target_service,
        "content service '" + str(service) + "' vs target_service '" + p.target_service + "'",
    )


# ---------- rollback ----------
def _validate_rollback(p):
    c = p.content
    service, frm, to = c.get("service"), c.get("from_version"), c.get("to_version")
    present = all(isinstance(x, str) and x for x in (service, frm, to))
    checks = [_check("fields_present", present, "needs service, from_version and to_version")]
    if not present:
        return checks, ""
    checks.append(_same_service(p, service))

    conn = _seeded_db()
    try:
        rows = conn.execute(
            "SELECT version, deployed_at, status FROM deployments WHERE service = ? "
            "ORDER BY deployed_at DESC", (service,)
        ).fetchall()
    finally:
        conn.close()

    checks.append(_check("service_has_deployments", bool(rows), str(len(rows)) + " deployments found for " + service))
    if not rows:
        return checks, ""
    latest = rows[0]
    checks.append(_check("from_is_latest", latest[0] == frm,
                         "latest deployed version is " + latest[0] + ", you asked to roll back from " + frm))
    target = next((r for r in rows if r[0] == to), None)
    checks.append(_check("target_exists", target is not None,
                         "known versions: " + ", ".join(r[0] for r in rows)))
    if target is not None:
        ok = target[1] < latest[1] and target[2] == "success"
        checks.append(_check("target_is_older_and_healthy", ok,
                             to + " deployed " + target[1] + " with status " + target[2]))
    return checks, "ROLLBACK " + str(service) + ": " + str(frm) + " -> " + str(to)


# ---------- config change ----------
def _validate_config(p):
    c = p.content
    service, changes = c.get("service"), c.get("changes")
    current = CURRENT_CONFIG.get(service) if isinstance(service, str) else None
    checks = [_check("service_known", current is not None,
                     "known services: " + ", ".join(CURRENT_CONFIG))]
    has_changes = isinstance(changes, dict) and bool(changes)
    checks.append(_check("changes_present", has_changes, "changes must be a non-empty object"))
    if current is None or not has_changes:
        return checks, ""
    checks.append(_same_service(p, service))

    lines = []
    for key, new in changes.items():
        if key not in current:
            checks.append(_check("key_exists:" + key, False,
                                 "unknown setting. Known: " + ", ".join(current)))
            continue
        if isinstance(new, bool) or not isinstance(new, int):
            checks.append(_check("type:" + key, False, "value must be an integer"))
            continue
        low, high = CONFIG_RULES[key]
        checks.append(_check("range:" + key, low <= new <= high,
                             str(new) + " must be between " + str(low) + " and " + str(high)))
        old = current[key]
        if key in DOUBLE_LIMIT_KEYS and old > 0:
            checks.append(_check("max_2x_increase:" + key, new <= old * 2,
                                 "new value " + str(new) + " vs current " + str(old) + " (limit 2x)"))
        lines.append(key + ": " + str(old) + " -> " + str(new))
    return checks, "CONFIG " + str(service) + "\n" + "\n".join(lines)


# ---------- SQL patch ----------
def _snapshot(conn):
    return {t: conn.execute("SELECT * FROM " + t).fetchall() for t in TABLES}


def _validate_sql(p):
    stmts = p.content.get("statements")
    shape_ok = (isinstance(stmts, list) and 0 < len(stmts) <= MAX_STATEMENTS
                and all(isinstance(s, str) for s in stmts))
    checks = [_check("statements_present", shape_ok,
                     "1 to " + str(MAX_STATEMENTS) + " SQL statements as a list of strings")]
    if not shape_ok:
        return checks, ""

    cleaned = [s.strip().rstrip(";").strip() for s in stmts]
    for i, s in enumerate(cleaned, 1):
        low = s.lower()
        problems = []
        if not low.startswith(ALLOWED_SQL_START):
            problems.append("must start with UPDATE, INSERT, DELETE or CREATE INDEX")
        if ";" in s:
            problems.append("only one statement per list item")
        if FORBIDDEN_SQL.search(s):
            problems.append("contains a forbidden keyword")
        if low.startswith(("update", "delete")) and not re.search(r"\bwhere\b", low):
            problems.append("UPDATE and DELETE need a WHERE clause")
        checks.append(_check("statement_" + str(i) + "_safe", not problems, "; ".join(problems) or "ok"))
    if not all(c.passed for c in checks):
        return checks, ""

    run_error, total = None, 0
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        conn.executescript(SEED_SQL)
        before = _snapshot(conn)
        conn.execute("BEGIN")
        try:
            for s in cleaned:
                total += max(conn.execute(s).rowcount, 0)
        except sqlite3.Error as e:
            run_error = str(e)
        finally:
            conn.execute("ROLLBACK")
        after = _snapshot(conn)
    finally:
        conn.close()

    checks.append(_check("dry_run_executes", run_error is None, run_error or "all statements ran"))
    if run_error is None:
        checks.append(_check("rows_affected_limit", total <= MAX_ROWS_AFFECTED,
                             str(total) + " rows affected (limit " + str(MAX_ROWS_AFFECTED) + ")"))
        checks.append(_check("rolled_back_cleanly", before == after, "sandbox data unchanged after dry run"))
    return checks, "SQL dry run, rows affected: " + str(total) + "\n" + "\n".join(cleaned)


# ---------- code diff ----------
def _banned_constructs(tree):
    bad = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_MODULES:
                    bad.add("import " + alias.name)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in BANNED_MODULES:
                bad.add("import from " + str(node.module))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALLS:
                bad.add("call to " + node.func.id)
    return sorted(bad)


def _validate_code(p):
    edits = p.content.get("edits")
    shape_ok = (isinstance(edits, list) and 0 < len(edits) <= MAX_EDITS
                and all(isinstance(e, dict) for e in edits))
    checks = [_check("edits_present", shape_ok,
                     "1 to " + str(MAX_EDITS) + " edits, each with file, old and new")]
    if not shape_ok:
        return checks, ""

    working = dict(REPO)
    touched = []
    for i, e in enumerate(edits, 1):
        label = "edit_" + str(i)
        path, old, new = e.get("file"), e.get("old"), e.get("new")
        if not (isinstance(path, str) and isinstance(old, str) and isinstance(new, str)):
            checks.append(_check(label, False, "file, old and new must all be strings"))
            continue
        if path not in working:
            checks.append(_check(label, False, "file '" + path + "' is not in the repository. Available: "
                                 + ", ".join(working)))
            continue
        if "services/" + p.target_service + "/" not in path:
            checks.append(_check(label, False, "file does not belong to target_service '" + p.target_service + "'"))
            continue
        old_n, new_n = _norm(old), _norm(new)
        count = working[path].count(old_n) if old_n else 0
        if count != 1:
            checks.append(_check(label, False, "old text found " + str(count)
                                 + " times, it must appear exactly once. Copy it exactly from the source file."))
            continue
        working[path] = working[path].replace(old_n, new_n, 1)
        touched.append(path)
        checks.append(_check(label, True, "applies cleanly to " + path))
    if not all(c.passed for c in checks):
        return checks, ""

    diffs, changed = [], 0
    for path in sorted(set(touched)):
        new_src = working[path]
        try:
            tree = ast.parse(new_src)
            checks.append(_check("syntax:" + path, True, "parses"))
            bad = _banned_constructs(tree)
            checks.append(_check("no_dangerous_code:" + path, not bad, ", ".join(bad) or "ok"))
            _clean, counts = redact(new_src)
            checks.append(_check("no_secrets:" + path, not counts, "secret or PII-like text found: " + str(counts) if counts else "ok"))
        except SyntaxError as e:
            checks.append(_check("syntax:" + path, False, "syntax error: " + str(e)))
        diff = list(difflib.unified_diff(
            REPO[path].split("\n"), new_src.split("\n"),
            fromfile="a/" + path, tofile="b/" + path, lineterm=""))
        diffs.append("\n".join(diff))
        changed += sum(1 for line in diff
                       if line[:1] in "+-" and not line.startswith(("+++", "---")))
    checks.append(_check("changes_something", changed > 0, str(changed) + " changed lines"))
    checks.append(_check("small_change", changed <= MAX_CHANGED_LINES,
                         str(changed) + " changed lines (limit " + str(MAX_CHANGED_LINES) + ")"))
    return checks, "\n".join(diffs)


HANDLERS = {
    "rollback": _validate_rollback,
    "config_change": _validate_config,
    "sql_patch": _validate_sql,
    "code_diff": _validate_code,
}


def validate_fix(proposal: FixProposal) -> SandboxResult:
    """Never raises. Anything unexpected becomes a failed check."""
    try:
        checks, preview = HANDLERS[proposal.fix_type.value](proposal)
    except Exception as e:
        checks = [_check("sandbox_internal_error", False, str(e))]
        preview = ""
    passed = bool(checks) and all(c.passed for c in checks)
    return SandboxResult(passed=passed, fix_type=proposal.fix_type.value,
                         checks=checks, preview=preview[:1500])