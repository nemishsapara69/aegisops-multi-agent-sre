import httpx
import openai
import pytest

from app.resilience import llm_events
from app.resilience.resilient_llm import AllModelsFailed, ResilientLLM
from app.resilience.retry import backoff_delay, classify_error

REQ = httpx.Request("POST", "https://api.example.com/v1/chat/completions")


def status_error(cls, code, headers=None):
    response = httpx.Response(code, headers=headers or {}, request=REQ)
    return cls("error " + str(code), response=response, body=None)


RATE = status_error(openai.RateLimitError, 429)
NOT_FOUND = status_error(openai.NotFoundError, 404)


@pytest.fixture(autouse=True)
def clean_events():
    llm_events.EVENTS.clear()
    yield
    llm_events.EVENTS.clear()


# ---- error classification ----
def test_rate_limit_is_transient():
    assert classify_error(RATE) == "transient"


def test_server_and_connection_errors_are_transient():
    assert classify_error(status_error(openai.InternalServerError, 503)) == "transient"
    assert classify_error(openai.APITimeoutError(request=REQ)) == "transient"
    assert classify_error(openai.APIConnectionError(request=REQ)) == "transient"


def test_long_retry_after_skips_model():
    err = status_error(openai.RateLimitError, 429, {"retry-after": "600"})
    assert classify_error(err) == "skip_model"


def test_short_retry_after_is_transient():
    err = status_error(openai.RateLimitError, 429, {"retry-after": "3"})
    assert classify_error(err) == "transient"


def test_auth_errors_are_fatal():
    assert classify_error(status_error(openai.AuthenticationError, 401)) == "fatal"
    assert classify_error(status_error(openai.PermissionDeniedError, 403)) == "fatal"


def test_bad_model_errors_skip_model():
    assert classify_error(NOT_FOUND) == "skip_model"
    assert classify_error(status_error(openai.BadRequestError, 400)) == "skip_model"


def test_unknown_errors_are_fatal():
    assert classify_error(ValueError("bug")) == "fatal"


def test_backoff_doubles_and_caps():
    assert backoff_delay(1, base=1.0, max_delay=20.0) == 1.0
    assert backoff_delay(2, base=1.0, max_delay=20.0) == 2.0
    assert backoff_delay(3, base=1.0, max_delay=20.0) == 4.0
    assert backoff_delay(10, base=1.0, max_delay=20.0) == 20.0


def test_backoff_honors_retry_after():
    assert backoff_delay(1, retry_after=7.0, base=1.0, max_delay=20.0) == 7.0


# ---- ResilientLLM ----
class FakeReply:
    def __init__(self, content="ok", usage=None):
        self.content = content
        self.usage_metadata = usage or {}


class FakeChat:
    def __init__(self, name, script, calls):
        self.name = name
        self.script = script
        self.calls = calls
        self.tools = None

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.calls.append(self.name)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


def make_llm(scripts):
    calls, chats, slept = [], {}, []

    def factory(model):
        chats[model] = FakeChat(model, scripts[model], calls)
        return chats[model]

    llm = ResilientLLM(factory, list(scripts), sleep=slept.append, jitter=False)
    return llm, calls, slept, chats


def test_success_first_try():
    llm, calls, slept, _ = make_llm({"a": [FakeReply("hi")]})
    assert llm.invoke("x").content == "hi"
    assert calls == ["a"] and slept == [] and llm.last_model == "a"


def test_transient_then_success():
    llm, calls, slept, _ = make_llm({"a": [RATE, FakeReply()]})
    llm.invoke("x")
    assert calls == ["a", "a"] and slept == [1.0]


def test_backoff_grows_then_falls_back():
    llm, calls, slept, _ = make_llm({"a": [RATE], "b": [FakeReply()]})
    llm.invoke("x")
    assert calls == ["a", "a", "a", "b"]
    assert slept == [1.0, 2.0]
    assert llm.last_model == "b"


def test_skip_model_error_falls_back_without_sleeping():
    llm, calls, slept, _ = make_llm({"a": [NOT_FOUND], "b": [FakeReply()]})
    llm.invoke("x")
    assert calls == ["a", "b"] and slept == []


def test_fatal_error_raises_immediately():
    auth = status_error(openai.AuthenticationError, 401)
    llm, calls, slept, _ = make_llm({"a": [auth], "b": [FakeReply()]})
    with pytest.raises(openai.AuthenticationError):
        llm.invoke("x")
    assert calls == ["a"]


def test_long_retry_after_skips_without_waiting():
    daily = status_error(openai.RateLimitError, 429, {"retry-after": "600"})
    llm, calls, slept, _ = make_llm({"a": [daily], "b": [FakeReply()]})
    llm.invoke("x")
    assert calls == ["a", "b"] and slept == []


def test_all_models_failing_raises():
    llm, calls, slept, _ = make_llm({"a": [RATE], "b": [RATE]})
    with pytest.raises(AllModelsFailed) as info:
        llm.invoke("x")
    assert isinstance(info.value.__cause__, openai.RateLimitError)
    assert slept == [1.0, 2.0, 1.0, 2.0]


def test_unknown_error_is_not_swallowed():
    llm, calls, slept, _ = make_llm({"a": [ValueError("bug")], "b": [FakeReply()]})
    with pytest.raises(ValueError):
        llm.invoke("x")
    assert calls == ["a"]


def test_bind_tools_applies_to_every_model():
    llm, calls, slept, chats = make_llm({"a": [NOT_FOUND], "b": [FakeReply()]})
    bound = llm.bind_tools(["TOOL"])
    bound.invoke("x")
    assert chats["a"].tools == ["TOOL"] and chats["b"].tools == ["TOOL"]
    assert bound.last_model == "b" and llm.last_model is None


def test_events_recorded_with_tokens():
    reply = FakeReply(usage={"input_tokens": 10, "output_tokens": 5})
    llm, _, _, _ = make_llm({"a": [RATE, reply]})
    llm.invoke("x")
    events = list(llm_events.EVENTS)
    assert [e["outcome"] for e in events] == ["transient", "success"]
    assert events[-1]["model"] == "a"
    assert events[-1]["input_tokens"] == 10 and events[-1]["output_tokens"] == 5
    assert "RateLimitError" in events[0]["error"]


def test_listener_errors_do_not_break_calls():
    def boom(event):
        raise RuntimeError("listener bug")

    llm_events.add_listener(boom)
    try:
        llm, _, _, _ = make_llm({"a": [FakeReply("fine")]})
        assert llm.invoke("x").content == "fine"
    finally:
        llm_events.remove_listener(boom)