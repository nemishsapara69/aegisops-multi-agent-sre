from dashboard import client, logic


def ev(seq, kind, agent=None, ok=True, payload=None, latency=None, summary="", tin=0, tout=0):
    return {"seq": seq, "event_type": kind, "agent": agent, "ok": ok, "payload": payload or {},
            "latency_ms": latency, "summary": summary, "input_tokens": tin, "output_tokens": tout}


def step(seq, agent, **kw):
    return ev(seq, "agent_step", agent, **kw)


def test_nothing_done_means_triage_is_running():
    state = logic.agent_status([])
    assert state["triage"] == "running"
    assert all(state[a] == "waiting" for a in logic.AGENTS[1:])


def test_next_agent_is_running():
    state = logic.agent_status([step(1, "triage"), step(2, "investigator")])
    assert state["triage"] == "done" and state["investigator"] == "done"
    assert state["memory"] == "running" and state["remediation"] == "waiting"


def test_pause_shows_governance_waiting_for_a_human():
    events = [step(i, a) for i, a in enumerate(logic.AGENTS[:4], 1)]
    events.append(ev(5, "approval_requested", "governance"))
    state = logic.agent_status(events)
    assert state["governance"] == "paused"
    assert "running" not in state.values()


def test_after_approval_governance_is_done():
    events = [step(i, a) for i, a in enumerate(logic.AGENTS, 1)]
    events.insert(4, ev(5, "approval_requested", "governance"))
    assert logic.agent_status(events, finished=True)["governance"] == "done"


def test_failed_step_is_marked():
    assert logic.agent_status([step(1, "triage", ok=False)])["triage"] == "failed"


def test_finished_run_has_no_running_agent():
    assert "running" not in logic.agent_status([step(1, "triage")], finished=True).values()


def test_summary_from_events():
    events = [
        step(1, "triage", payload={"priority": "P1", "category": "database"}),
        step(2, "investigator", payload={"root_cause": "leak in v2.14.0", "confidence": 0.9}),
        step(3, "memory", payload={"doc_ids": ["PM-1", "RB-1"]}),
        step(4, "remediation", payload={"fix_summary": "roll back", "fix_type": "rollback", "validated": True}),
        ev(5, "approval", "governance", payload={"approver": "asha"}),
        step(6, "governance", payload={"decision": "approved_executed", "risk_score": 80,
                                       "risk_level": "high", "risk_factors": [{"name": "x", "points": 5}]}),
    ]
    s = logic.summary_from_events(events)
    assert s["priority"] == "P1" and s["root_cause"] == "leak in v2.14.0"
    assert s["memory_docs"] == ["PM-1", "RB-1"] and s["fix_validated"] is True
    assert s["decision"] == "approved_executed" and s["approver"] == "asha"
    assert s["risk_score"] == 80 and len(s["risk_factors"]) == 1


def test_latency_counts_only_agent_steps():
    events = [step(1, "triage", latency=100), step(2, "triage", latency=50),
              ev(3, "llm_call", "triage", latency=999), step(4, "memory", latency=10)]
    assert logic.latency_by_agent(events) == {"triage": 150, "memory": 10}


def test_tokens_skip_agents_without_llm_calls():
    usage = {"by_agent": {"triage": {"input_tokens": 300, "output_tokens": 200},
                          "memory": {"input_tokens": 0, "output_tokens": 0}}}
    assert logic.tokens_by_agent(usage) == {"triage": {"input": 300, "output": 200}}
    assert logic.tokens_by_agent(None) == {}


def test_step_rows():
    rows = logic.step_rows([step(1, "triage", ok=False, latency=5, summary="x", tin=3, tout=4)])
    assert rows[0]["ok"] == "FAIL" and rows[0]["tokens in/out"] == "3/4" and rows[0]["ms"] == 5


def test_users_are_parsed_and_malformed_entries_ignored(monkeypatch):
    monkeypatch.setenv("AEGIS_API_KEYS", "k1:asha:sre:approver,broken,k2:ravi:developer:member")
    found = client.users()
    assert [u["name"] for u in found] == ["asha", "ravi"]
    assert found[0]["perm"] == "approver"