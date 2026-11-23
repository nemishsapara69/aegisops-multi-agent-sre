import json
import sys
import uuid

from app.graph.builder import build_graph
from app.graph.runner import current_state, pending_approval, resume_incident, start_incident


SCENARIOS = {
    "prod": {
        "alert_id": "1", "source": "pagerduty", "environment": "production",
        "text": "Payments failing for all users. Error: connection pool exhausted on payments-db 10.0.0.5. "
                "Contact: rahul@shop.com",
    },
    "staging": {
        "alert_id": "2", "source": "monitoring", "environment": "staging",
        "text": "Minor issue in staging: some payment refund requests are slow and occasionally time out on "
                "payments-db pool. Only testers are affected and a workaround exists.",
    },
}

name = sys.argv[1] if len(sys.argv) > 1 else "prod"
alert = SCENARIOS[name]

app = build_graph()
thread = "demo-" + uuid.uuid4().hex[:8]

state = start_incident(app, alert, "sre", thread)
print("Priority :", state["triage"]["priority"], "| environment:", alert["environment"])
print("Ran      :", state["completed"])
print("ROOT CAUSE:", state["investigation"]["root_cause"])

fix = state["fix_proposal"]
print("FIX      :", fix["validated"], "|", (fix.get("proposal") or {}).get("summary"))

payload = pending_approval(app, thread)
if payload is not None:
    print()
    print("=== PAUSED: HUMAN APPROVAL REQUIRED ===")
    for reason in payload.get("reasons", []):
        print("WHY :", reason)
    print("RISK:", payload["risk"]["score"], payload["risk"]["level"])
    for f in payload["risk"]["factors"]:
        print("   +%d %s (%s)" % (f["points"], f["name"], f["detail"]))
    print("FIX :", json.dumps(payload["fix"], indent=2))
    answer = input("Type approve or reject: ").strip()
    approver = input("Your name: ").strip()
    state = resume_incident(app, thread, {"decision": answer, "approver": approver, "comment": "demo"})

gov = state["governance"]
print()
print("=== RESULT ===")
print("DECISION  :", gov["decision"])
print("REASON    :", gov["reason"])
print("STATUS    :", state["status"])
if gov.get("execution"):
    print("EXECUTION :", gov["execution"]["message"])
print("RISK      :", state["risk"].get("score"), state["risk"].get("level"))
print("ERRORS    :", state["errors"])
print()
print("AUDIT TRAIL: python show_audit.py", thread)