import json
import os

base = os.path.join("evals", "results")

print("TRIAGE MISSES")
with open(os.path.join(base, "triage.jsonl"), encoding="utf-8") as fh:
    for line in fh:
        r = json.loads(line)
        if r["pred"] != r["label"]:
            print(r["id"], "| label", r["label"], "-> predicted", r["pred"], "|", r["tag"], "|", r["environment"])

print()
print("E2E RUNS (the file keeps every run, including earlier ones)")
with open(os.path.join(base, "e2e.jsonl"), encoding="utf-8") as fh:
    for line in fh:
        r = json.loads(line)
        print("run", r["run"], "| degraded", r["degraded"], "| llm attempts", r["llm_attempts"],
              "| models", r["models"], "| tokens", r["input_tokens"] + r["output_tokens"],
              "| fix", r["fix_type"])