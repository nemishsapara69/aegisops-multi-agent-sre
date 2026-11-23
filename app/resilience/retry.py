import openai

from app.resilience.limits import LLM_BASE_DELAY_SECONDS, LLM_MAX_DELAY_SECONDS


def retry_after_seconds(exc):
    """Reads the Retry-After header of an API error, or returns None."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def classify_error(exc, max_wait=LLM_MAX_DELAY_SECONDS):
    """transient = retry the same model, skip_model = try the next model, fatal = raise now."""
    if isinstance(exc, openai.RateLimitError):
        wait = retry_after_seconds(exc)
        if wait is not None and wait > max_wait:
            return "skip_model"          # e.g. daily limit: waiting is pointless
        return "transient"
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)):
        return "transient"
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return "fatal"
    if isinstance(exc, (openai.NotFoundError, openai.BadRequestError, openai.UnprocessableEntityError)):
        return "skip_model"
    return "fatal"                        # unknown errors are bugs, never hide them


def backoff_delay(attempt, retry_after=None, base=LLM_BASE_DELAY_SECONDS, max_delay=LLM_MAX_DELAY_SECONDS):
    delay = base * (2 ** (attempt - 1))
    if retry_after is not None:
        delay = max(delay, retry_after)
    return min(delay, max_delay)