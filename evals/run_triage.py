import argparse
import json
import os
import random
import time

from app.agents.triage_router import triage_node
from evals import data, judge


def load_rows(path):
    rows = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    rows[row["id"]] = row
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="only run this many new alerts")
    parser.add_argument("--pace", type=float, default=4.0, help="seconds to wait between alerts")
    parser.add_argument("--fresh", action="store_true", help="ignore and delete earlier results")
    args = parser.parse_args()

    path = os.path.join(judge.results_dir(), "triage.jsonl")
    if args.fresh and os.path.exists(path):
        os.remove(path)
    done = load_rows(path)

    items = list(data.TRIAGE)
    random.Random(7).shuffle(items)                      # fixed order, so --limit samples every priority
    todo = [i for i in items if i["id"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print("already done: %d | running now: %d | total: %d" % (len(done), len(todo), len(items)))

    for item in todo:
        alert = {"alert_id": item["id"], "source": item["source"],
                 "environment": item["environment"], "text": item["text"]}
        out, error = None, ""
        with judge.capture_events() as cap:
            started = time.time()
            try:
                out = triage_node({"raw_alert": alert})
            except Exception as exc:
                error = type(exc).__name__ + ": " + str(exc)[:120]
            latency = int((time.time() - started) * 1000)
        if out is None:
            print("%s CRASHED (not recorded, re-run to retry): %s" % (item["id"], error))
            time.sleep(args.pace)
            continue

        tri = out["triage"]
        pred = tri["priority"]
        sanitized = out.get("sanitized_text", "")
        row = {
            "id": item["id"], "label": item["label"], "pred": pred, "tag": item["tag"],
            "environment": item["environment"],
            "pii_leak": any(p in sanitized for p in item["pii"]),
            "fallback": str(tri.get("reasoning", "")).startswith("Triage failed"),
            "retries": len(out.get("errors") or []),
            "injection_ok": judge.injection_ok(item["label"], pred) if item["tag"] == "injection" else None,
            "input_tokens": sum(e.get("input_tokens") or 0 for e in cap.events),
            "output_tokens": sum(e.get("output_tokens") or 0 for e in cap.events),
            "latency_ms": latency, "llm_attempts": len(cap.events),
            "models": sorted({e.get("model") for e in cap.events}),
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        done[item["id"]] = row
        print("%s %-9s label %s -> %s %s" % (item["id"], item["tag"], item["label"], pred,
                                             "ok" if pred == item["label"] else "MISS"))
        time.sleep(args.pace)

    rows = list(done.values())
    s = judge.summarize_triage(rows)
    if not rows:
        return
    print()
    print("ALERTS %d of %d%s" % (s["alerts"], len(items), "" if s["alerts"] == len(items) else "  (PARTIAL RUN)"))
    print("exact accuracy      :", s["exact_accuracy_pct"], "%")
    print("within one level    :", s["within_one_level_pct"], "%")
    print("under-triaged       :", s["under_triaged_pct"], "% | over-triaged:", s["over_triaged_pct"], "%")
    print("SEVERE under-triage :", s["severe_under_triage"], "(a real P1/P2 labeled P3/P4, must be 0)")
    print("recall by label     :", s["recall_by_label_pct"])
    print("injection resisted  : %d of %d" % (s["injection_resisted"], s["injection_cases"]))
    print("PII leaks           :", s["pii_leaks"], "| fallback used:", s["fallback_used"])
    print("tokens per alert    : %s in / %s out" % (s["avg_input_tokens"], s["avg_output_tokens"]))
    print("confusion (rows = label, columns = predicted):")
    for label in judge.PRIORITIES:
        print("   ", label, s["confusion"][label])
    print("saved:", judge.save_summary("triage", s))


if __name__ == "__main__":
    main()