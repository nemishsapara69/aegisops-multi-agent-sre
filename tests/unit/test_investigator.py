from app.agents import investigator


class FakeAI:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def call(name, args, cid="c1"):
    return FakeAI(tool_calls=[{"name": name, "args": args, "id": cid}])


class FakeLLM:
    """Replays scripted replies; the last one repeats forever."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


STATE = {
    "triage": {"priority": "P1", "category": "database", "affected_service": "payments-db"},
    "sanitized_text": "Payments failing for all users, connection pool exhausted",
}

TOOL_DB = call("query_db", {"sql": "SELECT * FROM deployments"})
TOOL_LOGS = call("search_logs", {"service": "payments-api", "keyword": "checkout"})

REPORT_ARGS = {
    "root_cause": "v2.14.0 leaks DB connections",
    "confidence": 0.9,
    "evidence": [{"source": "query_db", "detail": "v2.14.0 deployed 02:35"}],
    "suggested_fix_area": "roll back v2.14.0",
    "needs_human": False,
}
FINAL = call("submit_report", REPORT_ARGS)


def use_fake(monkeypatch, replies):
    fake = FakeLLM(replies)
    monkeypatch.setattr(investigator, "get_llm", lambda *a, **k: fake)
    return fake


def test_tool_then_final(monkeypatch):
    use_fake(monkeypatch, [TOOL_DB, FINAL])
    out = investigator.investigator_node(dict(STATE))
    inv = out["investigation"]
    assert "leaks" in inv["root_cause"]
    assert inv["tool_calls_used"] == 1
    assert inv["tool_trace"][0]["ok"] is True
    assert out["completed"] == ["investigator"]
    assert out["iteration_count"] == 1
    assert out["errors"] == []


def test_tool_output_is_redacted_before_llm(monkeypatch):
    fake = use_fake(monkeypatch, [TOOL_LOGS, FINAL])
    investigator.investigator_node(dict(STATE))
    second_call = str(fake.calls[1])
    assert "rahul@shop.com" not in second_call
    assert "10.0.0.5" not in second_call
    assert "[EMAIL_REDACTED]" in second_call


def test_max_tool_calls_enforced(monkeypatch):
    use_fake(monkeypatch, [TOOL_DB])            # asks for a data tool forever
    out = investigator.investigator_node(dict(STATE))
    inv = out["investigation"]
    assert len(inv["tool_trace"]) == investigator.MAX_TOOL_CALLS
    assert inv["needs_human"] is True
    assert inv["confidence"] == 0.0


def test_tool_timeout_is_handled(monkeypatch):
    import time

    def slow_tool(sql):
        time.sleep(1)
        return "late"

    monkeypatch.setattr(investigator, "TOOLS", {"query_db": slow_tool})
    monkeypatch.setattr(investigator, "TOOL_TIMEOUT_SECONDS", 0.1)
    use_fake(monkeypatch, [TOOL_DB, FINAL])
    out = investigator.investigator_node(dict(STATE))
    assert out["investigation"]["tool_trace"][0]["ok"] is False
    assert out["investigation"]["root_cause"] != ""


def test_reply_without_tool_call_is_retried(monkeypatch):
    use_fake(monkeypatch, [FakeAI(content="I think it is the network"), FINAL])
    out = investigator.investigator_node(dict(STATE))
    assert len(out["errors"]) == 1
    assert out["investigation"]["needs_human"] is False


def test_invalid_final_is_retried(monkeypatch):
    bad = call("submit_report", dict(REPORT_ARGS, confidence=7))   # must be 0 to 1
    use_fake(monkeypatch, [bad, FINAL])
    out = investigator.investigator_node(dict(STATE))
    assert len(out["errors"]) == 1
    assert out["investigation"]["confidence"] == 0.9


def test_unknown_tool_does_not_crash(monkeypatch):
    use_fake(monkeypatch, [call("delete_everything", {}), FINAL])
    out = investigator.investigator_node(dict(STATE))
    assert out["investigation"]["tool_trace"][0]["ok"] is False