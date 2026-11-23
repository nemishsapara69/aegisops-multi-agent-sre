from app import llm


def test_default_chain_includes_backup(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert llm.get_llm().models == [llm.BIG_MODEL, llm.FAST_MODEL, llm.BACKUP_MODEL]


def test_fast_model_chain_starts_with_fast(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert llm.get_llm(llm.FAST_MODEL).models == [llm.FAST_MODEL, llm.BIG_MODEL, llm.BACKUP_MODEL]


def test_tool_chain_excludes_backup(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    models = llm.get_llm(for_tools=True).models
    assert llm.BACKUP_MODEL not in models
    assert models[0] == llm.BIG_MODEL


def test_empty_fallbacks_disables_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert llm.get_llm(fallbacks=[]).models == [llm.BIG_MODEL]


def test_missing_key_gives_clear_error(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    try:
        llm.get_llm()
        assert False, "expected KeyError"
    except KeyError as e:
        assert "GROQ_API_KEY" in str(e)