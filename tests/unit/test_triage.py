from app.agents import triage_router


class FakeReply:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return FakeReply(text)


GOOD = ('{"priority": "P1", "category": "database", "affected_service": "payments-db",'
        ' "reasoning": "Payments failing in production", "route": ["investigator", "memory"]}')

ALERT = {"alert_id": "a1", "source": "pagerduty", "environment": "production",
         "text": "Payments failing for rahul@shop.com on 10.0.0.5 key sk-abc123def456ghi789"}


def test_valid_reply(monkeypatch):
    fake = FakeLLM([GOOD])
    monkeypatch.setattr(triage_router, "get_llm", lambda *a, **k: fake)
    out = triage_router.triage_node({"raw_alert": ALERT})
    assert out["triage"]["priority"] == "P1"
    assert out["triage"]["route"][-1] == "governance"
    assert out["errors"] == []


def test_pii_never_reaches_llm(monkeypatch):
    fake = FakeLLM([GOOD])
    monkeypatch.setattr(triage_router, "get_llm", lambda *a, **k: fake)
    triage_router.triage_node({"raw_alert": ALERT})
    sent = str(fake.calls[0])
    assert "rahul@shop.com" not in sent
    assert "10.0.0.5" not in sent
    assert "sk-abc123def456ghi789" not in sent


def test_retry_then_success(monkeypatch):
    fake = FakeLLM(["this is not json", GOOD])
    monkeypatch.setattr(triage_router, "get_llm", lambda *a, **k: fake)
    out = triage_router.triage_node({"raw_alert": ALERT})
    assert out["triage"]["priority"] == "P1"
    assert len(out["errors"]) == 1
    assert len(fake.calls) == 2


def test_all_attempts_fail_uses_safe_fallback(monkeypatch):
    fake = FakeLLM(["garbage"])
    monkeypatch.setattr(triage_router, "get_llm", lambda *a, **k: fake)
    out = triage_router.triage_node({"raw_alert": ALERT})
    assert out["triage"]["priority"] == "P2"
    assert len(fake.calls) == 3
    assert len(out["errors"]) == 3


def test_invalid_priority_is_rejected_and_retried(monkeypatch):
    bad = GOOD.replace("P1", "P9")
    fake = FakeLLM([bad, GOOD])
    monkeypatch.setattr(triage_router, "get_llm", lambda *a, **k: fake)
    out = triage_router.triage_node({"raw_alert": ALERT})
    assert out["triage"]["priority"] == "P1"
    assert len(fake.calls) == 2

def test_route_is_decided_by_code(monkeypatch):
    # the LLM tries to skip memory, but P1 must always run the full pipeline
    reply = GOOD.replace('["investigator", "memory"]', '["governance"]')
    fake = FakeLLM([reply])
    monkeypatch.setattr(triage_router, "get_llm", lambda *a, **k: fake)
    out = triage_router.triage_node({"raw_alert": ALERT})
    assert out["triage"]["route"] == ["investigator", "memory", "remediation", "governance"]