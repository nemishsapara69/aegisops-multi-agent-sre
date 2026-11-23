from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Path, Query

from app.api import service
from app.api.schemas import AlertIn, ApprovalIn
from app.api.security import Principal, authenticate, require_approver
from app.observability import audit

app = FastAPI(
    title="AegisOps",
    version="1.0",
    description="Autonomous incident and SRE command center. Send your key in the X-API-Key header.",
)


def _not_found():
    return HTTPException(status_code=404, detail="Unknown incident.")


@app.get("/health")
def health():
    database_ok = True
    try:
        audit.list_incidents(1)
    except Exception:
        database_ok = False
    return {"status": "ok" if database_ok else "degraded", "database": database_ok,
            "audit_failures": audit.AUDIT_FAILURES["count"],
            "active_incidents": service.active_count()}


@app.post("/alerts", status_code=202)
def submit_alert(alert: AlertIn, background: BackgroundTasks,
                 principal: Principal = Depends(authenticate)):
    if not service.try_acquire_slot():
        raise HTTPException(status_code=429, detail="Too many incidents are running. Try again shortly.",
                            headers={"Retry-After": "30"})
    run_id = service.new_run_id()
    audit.upsert_incident(run_id, alert_id=alert.alert_id, environment=alert.environment,
                          user_role=principal.role, status="queued")
    audit.record_event(run_id, "alert_received", ok=True,
                       summary="alert received from " + alert.source,
                       payload={"source": alert.source, "alert_id": alert.alert_id,
                                "submitted_by": principal.name, "text_length": len(alert.text)})
    background.add_task(service.run_incident, run_id, alert.model_dump(), principal.role)
    return {"run_id": run_id, "status": "queued", "status_url": "/incidents/" + run_id}


@app.get("/incidents")
def list_incidents(limit: int = Query(20, ge=1, le=100), principal: Principal = Depends(authenticate)):
    return audit.list_incidents(limit=limit)


@app.get("/incidents/{run_id}")
def get_incident(run_id: str = Path(..., max_length=64), principal: Principal = Depends(authenticate)):
    view = service.incident_view(run_id)
    if view is None:
        raise _not_found()
    return view


@app.get("/incidents/{run_id}/audit")
def get_audit(run_id: str = Path(..., max_length=64), principal: Principal = Depends(authenticate)):
    if audit.get_incident(run_id) is None:
        raise _not_found()
    intact, first_bad = audit.verify_chain(run_id)
    return {"run_id": run_id, "events": audit.get_timeline(run_id),
            "usage": audit.usage_summary(run_id), "chain_intact": intact, "first_bad_event": first_bad}


@app.get("/approvals/pending")
def pending_approvals(principal: Principal = Depends(require_approver)):
    return service.pending_incidents()


@app.post("/approvals/{run_id}")
def decide(body: ApprovalIn, run_id: str = Path(..., max_length=64),
           principal: Principal = Depends(require_approver)):
    if audit.get_incident(run_id) is None:
        raise _not_found()
    try:
        service.submit_decision(run_id, body.decision, principal.name, body.comment)
    except service.AlreadyResolving:
        raise HTTPException(status_code=409, detail="A decision for this incident is already being processed.")
    except service.NotPending:
        raise HTTPException(status_code=409, detail="This incident is not waiting for approval.")
    return service.incident_view(run_id)