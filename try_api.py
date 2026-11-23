import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
BASE = os.environ.get("AEGIS_URL", "http://127.0.0.1:8000")
DONE = ("resolved_auto", "resolved_approved", "rejected", "escalated", "failed")


def users():
    out = []
    for part in os.environ.get("AEGIS_API_KEYS", "").split(","):
        bits = [b.strip() for b in part.strip().split(":")]
        if len(bits) == 4:
            out.append({"key": bits[0], "name": bits[1], "role": bits[2], "perm": bits[3]})
    return out


all_users = users()
approver = next((u for u in all_users if u["perm"] == "approver"), None)
member = next((u for u in all_users if u["perm"] != "approver"), None)
if approver is None or member is None:
    print("Add one approver and one member to AEGIS_API_KEYS in .env first.")
    sys.exit(1)


def headers(u):
    return {"X-API-Key": u["key"]}


c = httpx.Client(base_url=BASE, timeout=30)

print("health            :", c.get("/health").json())
print("no key            :", c.get("/incidents").status_code, "(expected 401)")

alert = {"alert_id": "api-demo", "source": "pagerduty", "environment": "production",
         "text": "Payments failing for all users. Error: connection pool exhausted on payments-db "
                 "10.0.0.5. Contact: rahul@shop.com"}
r = c.post("/alerts", headers=headers(member), json=alert)
print("submit as", member["name"], "  :", r.status_code, r.json())
run_id = r.json()["run_id"]

view = {}
for _ in range(90):
    view = c.get("/incidents/" + run_id, headers=headers(member)).json()
    if view.get("awaiting_approval") or view.get("status") in DONE:
        break
    time.sleep(2)
print("status            :", view["status"], "| priority:", view["priority"],
      "| awaiting approval:", view["awaiting_approval"])
print("root cause        :", view["root_cause"])
print("fix               :", view["fix"])
print("risk              :", view["risk"])

if view["awaiting_approval"]:
    r = c.post("/approvals/" + run_id, headers=headers(member), json={"decision": "approve"})
    print("member approves   :", r.status_code, "(expected 403)")
    pending = c.get("/approvals/pending", headers=headers(approver)).json()
    print("pending approvals :", [p["run_id"] for p in pending])
    r = c.post("/approvals/" + run_id, headers=headers(approver),
               json={"decision": "approve", "comment": "reviewed via API"})
    print("approver approves :", r.status_code, "|", r.json().get("decision"))
    r = c.post("/approvals/" + run_id, headers=headers(approver), json={"decision": "approve"})
    print("approve again     :", r.status_code, "(expected 409)")

a = c.get("/incidents/" + run_id + "/audit", headers=headers(member)).json()
print("audit events      :", len(a["events"]), "| chain intact:", a["chain_intact"])
print("tokens in/out     :", a["usage"]["total_input_tokens"], "/", a["usage"]["total_output_tokens"])