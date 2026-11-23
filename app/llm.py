import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from app.resilience.resilient_llm import ResilientLLM

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1"

BIG_MODEL = "openai/gpt-oss-120b"       # reasoning-heavy agents
FAST_MODEL = "openai/gpt-oss-20b"       # simple, high-volume steps
BACKUP_MODEL = "qwen/qwen3.8-27b"       # last resort

DEFAULT_ORDER = [BIG_MODEL, FAST_MODEL, BACKUP_MODEL]
TOOL_ORDER = [BIG_MODEL, FAST_MODEL]  

def _make_chat(model, temperature):
    return ChatOpenAI(
        base_url=GROQ_URL,
        api_key=os.environ["GROQ_API_KEY"],
        model=model,
        temperature=temperature,
        timeout=30,
        max_retries=0,          # retries are handled by ResilientLLM, not by the client
    )


def get_llm(model=BIG_MODEL, temperature=0, fallbacks=None, for_tools=False):
    """fallbacks=None uses the default chain, fallbacks=[] disables fallback.
    for_tools=True restricts the chain to models that handle native tool calls."""
    if not os.environ.get("GROQ_API_KEY"):
        raise KeyError("GROQ_API_KEY is not set. Add it to your .env file.")
    if fallbacks is None:
        pool = TOOL_ORDER if for_tools else DEFAULT_ORDER
        fallbacks = [m for m in pool if m != model]
    chain = [model] + [m for m in fallbacks if m != model]
    return ResilientLLM(lambda m: _make_chat(m, temperature), chain)