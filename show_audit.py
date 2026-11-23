import sys

from app.observability import audit

args = sys.argv[1:]
if not args:
    rows = audit.list_incidents(10)
    if not rows:
        print("No incidents recorded yet.")
        sys.exit(0)
    print("Latest incidents:")
    for r in rows:
        print("  %s | %s | %s | %s | %s" % (r["run_id"], r["priority"], r["environment"], r["status"], r["updated_at"]))
    print("Show one with: python show_audit.py <run_id>")
    sys.exit(0)

run_id = args[0]
inc = audit.get_incident(run_id)
if inc is None:
    print("Unknown run id:", run_id)
    sys.exit(1)

print("INCIDENT", run_id, "|", inc["priority"], "|", inc["environment"], "|", inc["status"])
print()
for e in audit.get_timeline(run_id):
    latency = "-" if e["latency_ms"] is None else str(e["latency_ms"])
    print("%3d %-18s %-13s %-5s %6s ms  tok %d/%d  %s" % (
        e["seq"], e["event_type"], e["agent"] or "-", "ok" if e["ok"] else "FAIL",
        latency, e["input_tokens"], e["output_tokens"], e["summary"][:90]))

u = audit.usage_summary(run_id)
print()
print("LLM CALLS:", u["llm_calls"], "| tokens in/out:", u["total_input_tokens"], "/", u["total_output_tokens"])
ok, bad = audit.verify_chain(run_id)
print("CHAIN INTEGRITY:", "intact" if ok else "BROKEN at event " + str(bad))