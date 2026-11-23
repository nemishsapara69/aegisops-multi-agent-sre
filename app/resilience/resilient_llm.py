import random
import time

from app.resilience import llm_events
from app.resilience.limits import LLM_MAX_ATTEMPTS_PER_MODEL
from app.resilience.retry import backoff_delay, classify_error, retry_after_seconds


class AllModelsFailed(Exception):
    pass


def _usage(reply):
    usage = getattr(reply, "usage_metadata", None) or {}
    try:
        return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    except Exception:
        return 0, 0


class ResilientLLM:
    """Looks like a chat model to the agents (invoke and bind_tools) but retries and falls back."""

    def __init__(self, factory, models, tools=None, sleep=time.sleep, jitter=True, max_attempts=None):
        self._factory = factory                  # model name -> chat model (with no retries of its own)
        self.models = list(models)
        self._tools = tools
        self._sleep = sleep
        self._jitter = jitter
        self._max_attempts = max_attempts or LLM_MAX_ATTEMPTS_PER_MODEL
        self.last_model = None

    def bind_tools(self, tools):
        return ResilientLLM(self._factory, self.models, tools=tools, sleep=self._sleep,
                            jitter=self._jitter, max_attempts=self._max_attempts)

    def _emit(self, model, attempt, outcome, started, error="", reply=None):
        tokens_in, tokens_out = _usage(reply) if reply is not None else (0, 0)
        llm_events.emit({
            "ts": time.time(),
            "model": model,
            "attempt": attempt,
            "outcome": outcome,                  # success / transient / skip_model / fatal
            "latency_ms": int((time.time() - started) * 1000),
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "error": error[:200],
        })

    def invoke(self, messages):
        last_error = None
        for model in self.models:
            chat = self._factory(model)
            if self._tools:
                chat = chat.bind_tools(self._tools)
            for attempt in range(1, self._max_attempts + 1):
                started = time.time()
                try:
                    reply = chat.invoke(messages)
                except Exception as exc:
                    last_error = exc
                    kind = classify_error(exc)
                    self._emit(model, attempt, kind, started, type(exc).__name__ + ": " + str(exc))
                    if kind == "fatal":
                        raise
                    if kind == "skip_model":
                        break
                    if attempt >= self._max_attempts:
                        break
                    delay = backoff_delay(attempt, retry_after_seconds(exc))
                    if self._jitter:
                        delay += random.uniform(0, delay * 0.25)
                    self._sleep(delay)
                    continue
                self._emit(model, attempt, "success", started, reply=reply)
                self.last_model = model
                return reply
        raise AllModelsFailed("All models failed: " + ", ".join(self.models)
                              + " | last error: " + str(last_error)[:200]) from last_error