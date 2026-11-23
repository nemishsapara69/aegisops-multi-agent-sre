import argparse
import json
import os
import time
import uuid

from app.graph.builder import build_graph
from app.graph.runner import pending_approval, resume_incident, start_incident
from app.tools.executor import EXECUTION_LOG
from evals import judge

ALERT = {
    "alert_id": "eval-payments", "source": "pagerduty", "environment": "production",
    "text": "Payments failing for all users. Error: connection pool exhausted on payments-db 10.0.0.5. "
            "Contact: rahul@shop.com",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--pace", type=float, default=30.0, help="seconds between runs (free-tier token limits)")
    args = parser.parse_args()

    path = os.path.join(judge.results_dir(), "e2e.jsonl")
    rows = []
    for i in range(1, args.runs + 1):
        EXECUTION_LOG.clear()
        run_id = "eval-" + uuid.uuid4().hex[:8]
        app = build_graph()
        row = None
        with judge.capture_events() as cap:
            started = time.time()
            try:
                state = start_incident(app, ALERT, "sre", run_id)
                paused = pending_approval(app, run_id) is not None
                executed_before = len(EXECUTION_LOG)
                final = state
                if paused:
                    final = resume_incident(app, run_id, {"decision": "approve", "approver": "eval-bot",
                                                          "comment": "evaluation run"})
                latency = int((time.time() - started) * 1000)
                rc_text = (final.get("investigation") or {}).get("root_cause", "")
                rc = judge.judge_root_cause(rc_text)
                fx = judge.judge_fix(final.get("fix_proposal"))
                errors = final.get("errors") or []
                row = {
                    "run": i, "run_id": run_id,
                    "priority": (final.get("triage") or {}).get("priority"),
                    "paused": paused, "executed_before_approval": executed_before,
                    "completed": (final.get("governance") or {}).get("decision") == "approved_executed",
                    "root_cause_hit": rc["hit"], "hallucinated": bool(rc["forbidden"]),
                    "fix_validated": fx["validated"], "fix_correct": fx["correct"],
                    "runbook_violation": fx["runbook_violation"], "fix_type": fx["fix_type"],
                    "agent_crashes": sum(1 for e in errors if "crashed" in e),
                    "root_cause": rc_text[:300],
                }
            except Exception as exc:
                print("run %d CRASHED: %s: %s" % (i, type(exc).__name__, str(exc)[:150]))
        if row is not None:
            row.update({
                "degraded": any(e.get("outcome") != "success" for e in cap.events),
                "llm_attempts": len(cap.events),
                "input_tokens": sum(e.get("input_tokens") or 0 for e in cap.events),
                "output_tokens": sum(e.get("output_tokens") or 0 for e in cap.events),
                "latency_ms": latency, "cost": judge.estimate_cost(cap.events),
                "models": sorted({e.get("model") for e in cap.events}),
            })
            rows.append(row)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            print("run %d: priority %s | paused %s | root cause %s | fix %s (%s) | %d tokens | %.1fs" % (
                i, row["priority"], row["paused"], "HIT" if row["root_cause_hit"] else "MISS",
                "correct" if row["fix_correct"] else "not correct", row["fix_type"],
                row["input_tokens"] + row["output_tokens"], row["latency_ms"] / 1000.0))
            if not row["root_cause_hit"]:
                print("   root cause was:", row["root_cause"])
        if i < args.runs:
            time.sleep(args.pace)

    if not rows:
        return
    s = judge.summarize_e2e(rows)
    print()
    for key, value in s.items():
        print("%-32s %s" % (key, value))
    print("saved:", judge.save_summary("e2e", s))


if __name__ == "__main__":
    main()