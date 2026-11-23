import os
import threading
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base

load_dotenv()

DEFAULT_URL = "sqlite:///aegisops_audit.db"
_lock = threading.Lock()
_state = {"engine": None, "factory": None}


def normalize_url(url):
    """Accept the common postgresql:// form and use the psycopg 3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def raw_postgres_url():
    """Plain postgresql:// URL for the LangGraph checkpointer, or None when not using Postgres."""
    url = os.environ.get("DATABASE_URL") or ""
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://"):]
    if url.startswith("postgresql://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return None


def configure(url=None):
    """(Re)creates the engine and the tables. Called lazily, and by tests."""
    url = normalize_url(url or os.environ.get("DATABASE_URL") or DEFAULT_URL)
    with _lock:
        if _state["engine"] is not None:
            _state["engine"].dispose()
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(url, **kwargs)
        Base.metadata.create_all(engine)
        _state["engine"] = engine
        _state["factory"] = sessionmaker(bind=engine, expire_on_commit=False)
    return engine


def reset():
    with _lock:
        if _state["engine"] is not None:
            _state["engine"].dispose()
        _state["engine"] = None
        _state["factory"] = None


def get_engine():
    if _state["engine"] is None:
        configure()
    return _state["engine"]


@contextmanager
def session_scope():
    get_engine()
    session = _state["factory"]()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()