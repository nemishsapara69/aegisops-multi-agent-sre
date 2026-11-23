import datetime
import json
import os

from evals import judge


def load(name):
    path = os.path.join(judge.results_dir(), name + "_summary.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def f(value, suffix=""):
    return "n/a" if value is None else str(value) + suffix


def build():
    lines = ["# AegisOps evaluation report", "", "Generated: " + datetime.date.today().isoformat(), ""]

    off = load("offline")
    lines += ["## 1. Component checks (deterministic, no LLM)", ""]
    if off:
        r, s, g, t = off["redaction"], off["sandbox"], off["governance"], off["retrieval"]
        lines += [
            "| Suite | Cases | Passed | Safety metric |", "|---|---|---|---|",
            "| PII redaction | %d | %d | secrets leaked: %d |" % (r["cases"], r["passed"], r["secrets_leaked"]),
            "| Fix sandbox | %d | %d | unsafe fixes accepted: %d |" % (s["cases"], s["passed"], s["false_accepts"]),
            "| Governance policy | %d | %d | P1/P2 combinations auto-executed: %d of %d |" % (
                g["cases"], g["cases"] - g["case_mismatches"], g["p1_p2_auto_executed"], g["p1_p2_combos"]),
            "| Retrieval and RBAC | %d | %d | RBAC leaks: %d in %d checks |" % (
                t["cases"], t["passed"], t["leaks"], t["leak_checks"]), ""]
    else:
        lines += ["Not run yet (`python -m evals.run_offline`).", ""]

    tri = load("triage")
    lines += ["## 2. Triage agent (LLM, labeled alerts)", ""]
    if tri and tri.get("alerts"):
        lines += [
            "| Metric | Value |", "|---|---|",
            "| Alerts evaluated | %d |" % tri["alerts"],
            "| Exact priority accuracy | %s |" % f(tri["exact_accuracy_pct"], "%"),
            "| Within one level | %s |" % f(tri["within_one_level_pct"], "%"),
            "| Under-triaged / over-triaged | %s / %s |" % (f(tri["under_triaged_pct"], "%"), f(tri["over_triaged_pct"], "%")),
            "| Severe under-triage (real P1/P2 labeled P3/P4) | %d |" % tri["severe_under_triage"],
            "| Prompt-injection attacks resisted | %d of %d |" % (tri["injection_resisted"], tri["injection_cases"]),
            "| PII leaks into the prompt | %d |" % tri["pii_leaks"],
            "| Fallback used (3 failed attempts) | %d |" % tri["fallback_used"],
            "| Tokens per alert (in / out) | %s / %s |" % (f(tri["avg_input_tokens"]), f(tri["avg_output_tokens"])),
            "| Latency p50 / p95 | %s ms / %s ms |" % (f(tri["latency_ms_p50"]), f(tri["latency_ms_p95"])), ""]
    else:
        lines += ["Not run yet (`python -m evals.run_triage`).", ""]

    e2e = load("e2e")
    lines += ["## 3. End to end (payments incident, repeated runs)", ""]
    if e2e and e2e.get("runs"):
        lines += [
            "| Metric | Value |", "|---|---|",
            "| Runs | %d |" % e2e["runs"],
            "| Root cause correct | %s |" % f(e2e["root_cause_hit_pct"], "%"),
            "| Hallucinated cause | %s |" % f(e2e["hallucination_pct"], "%"),
            "| Fix passed the sandbox | %s |" % f(e2e["fix_validated_pct"], "%"),
            "| Fix is the expected one | %s |" % f(e2e["fix_correct_pct"], "%"),
            "| Fix against the runbook | %s |" % f(e2e["runbook_violation_pct"], "%"),
            "| Paused for a human before executing | %s |" % f(e2e["paused_for_human_pct"], "%"),
            "| Executions before approval | %d |" % e2e["unsafe_pre_approval_executions"],
            "| Runs where an agent crashed | %d |" % e2e["runs_with_agent_crash"],
            "| Runs with LLM retries or fallbacks | %s |" % f(e2e["degraded_runs_pct"], "%"),
            "| Tokens per incident (in / out) | %s / %s |" % (f(e2e["avg_input_tokens"]), f(e2e["avg_output_tokens"])),
            "| Latency p50 / p95 | %s ms / %s ms |" % (f(e2e["latency_ms_p50"]), f(e2e["latency_ms_p95"])),
            "| Paid-equivalent cost per incident | %s |" % (
                "n/a (fill PRICES in evals/judge.py)" if e2e["avg_cost_usd"] is None else "$" + str(e2e["avg_cost_usd"])), ""]
    else:
        lines += ["Not run yet (`python -m evals.run_e2e`).", ""]

    lines += [
        "## Limitations", "",
        "- Labels were written by a single annotator (the author).",
        "- The datasets are synthetic and small. These are measurements on this set, not production accuracy.",
        "- The end-to-end evaluation uses one scenario, so it measures consistency, not generalization.",
        "- Root-cause and fix judging uses a strict keyword rubric, not a human or an LLM judge.",
        "- Latency includes retries and free-tier rate-limit waits.",
        "- Free-tier runs cost nothing. The paid-equivalent cost needs the provider's price list.", ""]
    return "\n".join(lines)


def main():
    text = build()
    with open("EVAL_REPORT.md", "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print("saved: EVAL_REPORT.md")


if __name__ == "__main__":
    main()