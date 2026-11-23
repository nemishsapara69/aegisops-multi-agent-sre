import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd
import streamlit as st

from dashboard import client, logic

st.set_page_config(page_title="AegisOps", page_icon="🛡️", layout="wide")

SAMPLE_PATH = os.path.join(ROOT, "dashboard", "sample_incident.json")
PAGES = ["Submit and watch", "Approvals", "Audit trail", "Incidents", "Replay (no tokens)"]

PRESETS = {
    "Production payments outage": {
        "environment": "production",
        "text": "Payments failing for all users. Error: connection pool exhausted on payments-db "
                "10.0.0.5. Contact: rahul@shop.com",
    },
    "Staging payments slowdown": {
        "environment": "staging",
        "text": "Minor issue in staging: some payment refund requests are slow and occasionally time out "
                "on the payments-db pool. Only testers are affected and a workaround exists.",
    },
}


def rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def flash(kind, text):
    st.session_state["flash"] = (kind, text)


def show_flash():
    item = st.session_state.pop("flash", None)
    if item:
        getattr(st, item[0])(item[1])


def need_user(user):
    if user is None:
        st.error("No API users found. Add AEGIS_API_KEYS to your .env file.")
        st.stop()


def api_error(code, data):
    st.error("API error " + str(code) + ": " + str(data.get("detail", data)))


def incident_label(inc):
    return "%s | %s | %s | %s" % (inc["run_id"], inc.get("priority"), inc.get("environment"), inc.get("status"))


def agent_boxes(state):
    cols = st.columns(len(logic.AGENTS))
    for col, agent in zip(cols, logic.AGENTS):
        col.markdown(logic.ICONS[state[agent]] + " **" + agent + "**")
        col.caption(logic.LABELS[state[agent]])


def risk_chart(factors):
    if factors:
        df = pd.DataFrame({"points": [f["points"] for f in factors]}, index=[f["name"] for f in factors])
        st.bar_chart(df)


# ---------------------------------------------------------------- approvals
def decide(user, run_id, decision, comment):
    code, data = client.call("POST", "/approvals/" + run_id, user["key"],
                             json={"decision": decision, "comment": comment})
    if code == 200:
        flash("success", "Recorded: " + str(data.get("decision")) + " (acting as " + user["name"] + ")")
        rerun()
    elif code == 403:
        st.error("403: the key for '" + user["name"] + "' is not allowed to approve or reject. "
                 "Nothing was executed.")
    else:
        api_error(code, data)


def approval_ui(user, run_id, payload, prefix):
    st.subheader("Human approval required")
    for reason in payload.get("reasons", []):
        st.warning(reason)
    risk = payload.get("risk") or {}
    st.write("**Risk score:** " + str(risk.get("score")) + " (" + str(risk.get("level")) + ")")
    risk_chart(risk.get("factors") or [])
    fix = payload.get("fix") or {}
    st.markdown("**Proposed fix:** " + str(fix.get("type")) + " on " + str(fix.get("target"))
                + ". " + str(fix.get("summary")))
    st.json(fix.get("content") or {})
    st.caption("Rollback plan: " + str(fix.get("rollback_plan")))
    if payload.get("sandbox_preview"):
        st.code(payload["sandbox_preview"])
    comment = st.text_input("Comment (optional)", key=prefix + "_comment_" + run_id)
    left, right = st.columns(2)
    if left.button("Approve", key=prefix + "_approve_" + run_id, type="primary"):
        decide(user, run_id, "approve", comment)
    if right.button("Reject", key=prefix + "_reject_" + run_id):
        decide(user, run_id, "reject", comment)


def page_approvals(user):
    need_user(user)
    st.header("Approval inbox")
    code, pending = client.call("GET", "/approvals/pending", user["key"])
    if code == 403:
        st.error("403: the key for '" + user["name"] + "' cannot see approvals. "
                 "Switch to an approver in the sidebar.")
        return
    if code != 200:
        api_error(code, pending)
        return
    if not pending:
        st.success("Nothing is waiting for a decision.")
        return
    for item in pending:
        title = "%s | %s | %s | risk %s" % (item["run_id"], item.get("priority"),
                                            item.get("environment"), item.get("risk_score"))
        with st.expander(title, expanded=len(pending) == 1):
            vcode, view = client.call("GET", "/incidents/" + item["run_id"], user["key"])
            if vcode == 200 and view.get("pending_approval"):
                st.write("**Root cause:** " + str(view.get("root_cause")))
                approval_ui(user, item["run_id"], view["pending_approval"], "inbox")
            else:
                st.info("This incident is no longer waiting.")


# ---------------------------------------------------------------- submit and watch
def draw_status(container, user, run_id):
    c1, view = client.call("GET", "/incidents/" + run_id, user["key"])
    c2, aud = client.call("GET", "/incidents/" + run_id + "/audit", user["key"])
    with container.container():
        if c1 != 200 or c2 != 200:
            api_error(c1 if c1 != 200 else c2, view if c1 != 200 else aud)
            return None, None
        events = aud["events"]
        finished = view.get("status") in logic.DONE_STATUSES
        agent_boxes(logic.agent_status(events, finished))
        a, b, c, d = st.columns(4)
        a.metric("Status", str(view.get("status")))
        b.metric("Priority", str(view.get("priority")))
        risk = view.get("risk") or {}
        c.metric("Risk", (str(risk.get("score")) + " " + str(risk.get("level"))) if risk else "-")
        usage = aud.get("usage") or {}
        d.metric("Tokens in/out", str(usage.get("total_input_tokens", 0)) + "/" + str(usage.get("total_output_tokens", 0)))
        if view.get("root_cause"):
            st.write("**Root cause:** " + str(view["root_cause"]))
        if view.get("fix"):
            st.write("**Fix:** " + str(view["fix"].get("summary")) + " (validated: " + str(view["fix"].get("validated")) + ")")
        if view.get("decision"):
            st.write("**Decision:** " + str(view["decision"]) + ". " + str(view.get("decision_reason")))
    return view, aud


def watch(user, run_id):
    box = st.empty()
    for _ in range(120):
        view, _aud = draw_status(box, user, run_id)
        if view is None:
            break
        if view.get("pending_approval") or view.get("status") in logic.DONE_STATUSES:
            break
        time.sleep(1.5)


def draw_controls(user, run_id):
    code, view = client.call("GET", "/incidents/" + run_id, user["key"])
    if code != 200:
        return
    if view.get("awaiting_approval") and view.get("pending_approval"):
        approval_ui(user, run_id, view["pending_approval"], "live")
    elif view.get("approval_orphaned"):
        st.warning("This approval was lost because the API restarted (the checkpointer is in memory).")


def page_submit(user):
    need_user(user)
    st.header("Submit an alert")
    st.caption("A live run uses about 10K tokens of your free LLM allowance. "
               "Use Replay to show an old run for free.")
    choice = st.radio("Preset", list(PRESETS.keys()) + ["Custom"], horizontal=True)
    if choice == "Custom":
        default_text, env = "", st.selectbox("Environment", ["production", "staging", "development"])
    else:
        default_text, env = PRESETS[choice]["text"], PRESETS[choice]["environment"]
        st.caption("Environment: " + env)
    text = st.text_area("Alert text", value=default_text, height=100, key="alert_text_" + choice)

    submitted = False
    if st.button("Submit alert", type="primary"):
        if not text.strip():
            st.error("Write some alert text first.")
        else:
            code, data = client.call("POST", "/alerts", user["key"], json={
                "alert_id": "dash-" + str(int(time.time())), "source": "dashboard",
                "text": text.strip(), "environment": env})
            if code != 202:
                api_error(code, data)
            else:
                st.session_state["run_id"] = data["run_id"]
                watch(user, data["run_id"])
                submitted = True

    run_id = st.session_state.get("run_id")
    if run_id:
        if not submitted:
            st.divider()
            st.caption("Last incident: " + run_id)
            st.button("Refresh status")
            draw_status(st.container(), user, run_id)
        draw_controls(user, run_id)


# ---------------------------------------------------------------- audit trail
def page_audit(user):
    need_user(user)
    st.header("Audit trail")
    code, incidents = client.call("GET", "/incidents?limit=50", user["key"])
    if code != 200:
        api_error(code, incidents)
        return
    if not incidents:
        st.info("No incidents yet.")
        return
    labels = [incident_label(i) for i in incidents]
    pick = st.selectbox("Incident", range(len(incidents)), format_func=lambda k: labels[k])
    run_id = incidents[pick]["run_id"]
    code, aud = client.call("GET", "/incidents/" + run_id + "/audit", user["key"])
    if code != 200:
        api_error(code, aud)
        return
    if aud["chain_intact"]:
        st.success("Hash chain intact: no event was changed or removed after it was written.")
    else:
        st.error("Hash chain BROKEN at event " + str(aud["first_bad_event"]) + ": the record was tampered with.")
    usage = aud["usage"]
    a, b, c = st.columns(3)
    a.metric("Events", len(aud["events"]))
    b.metric("LLM calls", usage["llm_calls"])
    c.metric("Tokens in/out", str(usage["total_input_tokens"]) + "/" + str(usage["total_output_tokens"]))

    tab1, tab2, tab3 = st.tabs(["Timeline", "Latency per agent", "Tokens per agent"])
    with tab1:
        st.dataframe(pd.DataFrame(logic.step_rows(aud["events"])))
    with tab2:
        latency = logic.latency_by_agent(aud["events"])
        if latency:
            st.bar_chart(pd.DataFrame({"ms": list(latency.values())}, index=list(latency.keys())))
    with tab3:
        tokens = logic.tokens_by_agent(usage)
        if tokens:
            st.bar_chart(pd.DataFrame(
                {"input": [v["input"] for v in tokens.values()], "output": [v["output"] for v in tokens.values()]},
                index=list(tokens.keys())))
        else:
            st.info("No LLM calls recorded for this incident.")


# ---------------------------------------------------------------- incident list
def page_incidents(user):
    need_user(user)
    st.header("Incidents")
    code, incidents = client.call("GET", "/incidents?limit=100", user["key"])
    if code != 200:
        api_error(code, incidents)
        return
    if not incidents:
        st.info("No incidents yet.")
        return
    df = pd.DataFrame(incidents)
    left, right = st.columns(2)
    priorities = left.multiselect("Priority", sorted(df["priority"].dropna().unique()))
    statuses = right.multiselect("Status", sorted(df["status"].dropna().unique()))
    if priorities:
        df = df[df["priority"].isin(priorities)]
    if statuses:
        df = df[df["status"].isin(statuses)]
    st.dataframe(df)


# ---------------------------------------------------------------- replay
def play(events, speed):
    box = st.empty()
    for i in range(1, len(events) + 1):
        part = events[:i]
        with box.container():
            agent_boxes(logic.agent_status(part, finished=(i == len(events))))
            st.dataframe(pd.DataFrame(logic.step_rows(part[-8:])))
        time.sleep(1.5 / speed)
    s = logic.summary_from_events(events)
    st.subheader("Result")
    a, b, c, d = st.columns(4)
    a.metric("Priority", str(s["priority"]))
    b.metric("Risk", (str(s["risk_score"]) + " " + str(s["risk_level"])) if s["risk_score"] is not None else "-")
    c.metric("Decision", str(s["decision"]))
    d.metric("Approver", str(s["approver"]))
    st.write("**Root cause:** " + str(s["root_cause"]))
    st.write("**Fix:** " + str(s["fix_summary"]) + " (validated: " + str(s["fix_validated"]) + ")")
    st.write("**Past incidents found:** " + ", ".join(s["memory_docs"]))
    risk_chart(s["risk_factors"])


def page_replay(user):
    st.header("Replay a saved incident")
    st.info("Replay reads saved audit events, so it uses no LLM tokens and works even if Groq is rate-limited.")
    source = st.radio("Source", ["Sample file (no server needed)", "Saved incident from the API"], horizontal=True)
    events = None
    if source.startswith("Sample"):
        if not os.path.exists(SAMPLE_PATH):
            st.warning("No sample file yet. Run: python export_sample.py <run_id>")
            return
        with open(SAMPLE_PATH, encoding="utf-8") as fh:
            events = json.load(fh)["events"]
    else:
        need_user(user)
        code, incidents = client.call("GET", "/incidents?limit=50", user["key"])
        if code != 200 or not incidents:
            st.warning("No incidents available from the API.")
            return
        labels = [incident_label(i) for i in incidents]
        pick = st.selectbox("Incident", range(len(incidents)), format_func=lambda k: labels[k])
        code, aud = client.call("GET", "/incidents/" + incidents[pick]["run_id"] + "/audit", user["key"])
        if code != 200:
            api_error(code, aud)
            return
        events = aud["events"]
    speed = st.slider("Speed", 1, 10, 3)
    if st.button("Play replay", type="primary"):
        play(events, speed)


# ---------------------------------------------------------------- main
def main():
    st.sidebar.title("🛡️ AegisOps")
    users = client.users()
    user = None
    if users:
        names = [u["name"] + " (" + u["role"] + ", " + u["perm"] + ")" for u in users]
        index = st.sidebar.selectbox("Act as", range(len(users)), format_func=lambda k: names[k])
        user = users[index]
    else:
        st.sidebar.warning("No AEGIS_API_KEYS found in .env")
    code, health = client.call("GET", "/health")
    if code == 200:
        st.sidebar.success("API: " + str(health.get("status")))
        st.sidebar.caption("Running incidents: " + str(health.get("active_incidents"))
                           + " | audit failures: " + str(health.get("audit_failures")))
    else:
        st.sidebar.error("API not reachable (Replay with the sample file still works)")
    page = st.sidebar.radio("Page", PAGES)

    show_flash()
    if page == PAGES[0]:
        page_submit(user)
    elif page == PAGES[1]:
        page_approvals(user)
    elif page == PAGES[2]:
        page_audit(user)
    elif page == PAGES[3]:
        page_incidents(user)
    else:
        page_replay(user)


main()