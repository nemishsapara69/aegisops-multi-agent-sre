import json
import os
import sys

from app.observability import audit

if len(sys.argv) < 2:
    print("Recent incidents:")
    for r in audit.list_incidents(15):
        print("  %s | %s | %s | %s" % (r["run_id"], r["priority"], r["environment"], r["status"]))
    print("Export one with: python export_sample.py <run_id>")
    sys.exit(0)

run_id = sys.argv[1]
if audit.get_incident(run_id) is None:
    print("Unknown run id:", run_id)
    sys.exit(1)

intact, _bad = audit.verify_chain(run_id)
data = {"run_id": run_id, "events": audit.get_timeline(run_id),
        "usage": audit.usage_summary(run_id), "chain_intact": intact}
path = os.path.join("dashboard", "sample_incident.json")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
print("saved", path, "|", len(data["events"]), "events | chain intact:", intact)