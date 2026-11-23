import hashlib
import json
import logging
from datetime import datetime

from app.db.models import AuditEvent, Incident
from app.db.session import session_scope
from app.security.pii_redactor import redact

log = logging.getLogger("aegisops.audit")
AUDIT_FAILURES = {"count": 0}      # audit is fail-open: failures are counted and logged, never raised
GENESIS = "0" * 64
MAX_PAYLOAD_CHARS = 20000


def scrub(obj):
    """JSON-safe copy of obj with emails, IPs and keys redacted. Everything stored goes through this."""
    text = json.dumps(obj, default=str, ensure_ascii=False)
    clean, _counts = redact(text)
    if len(clean) > MAX_PAYLOAD_CHARS:
        return {"_truncated": True}
    try:
        return json.loads(clean)
    except ValueError:
        return {"_unparseable": clean[:500]}


def hash_fields(e):
    return {
        "run_id": e.run_id, "seq": e.seq, "ts": e.ts.isoformat(), "event_type": e.event_type,
        "agent": e.agent, "ok": bool(e.ok), "summary": e.summary, "payload": e.payload,
        "latency_ms": e.latency_ms, "model": e.model,
        "input_tokens": e.input_tokens, "output_tokens": e.output_tokens,
    }


def compute_hash(prev_hash, fields):
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def record_event(run_id, event_type, agent=None, ok=True, summary="", payload=None,
                 latency_ms=None, model=None, input_tokens=0, output_tokens=0):
    """Appends one event to the run's hash chain. Returns False (never raises) on failure."""
    try:
        clean_payload = scrub(payload if payload is not None else {})
        clean_summary = redact(str(summary))[0][:500]
        with session_scope() as s:
            last = (s.query(AuditEvent).filter(AuditEvent.run_id == run_id)
                    .order_by(AuditEvent.seq.desc()).first())
            prev = last.hash if last else GENESIS
            ev = AuditEvent(
                run_id=run_id, seq=(last.seq + 1) if last else 1, ts=datetime.utcnow(),
                event_type=event_type, agent=agent, ok=bool(ok), summary=clean_summary,
                payload=clean_payload,
                latency_ms=int(latency_ms) if latency_ms is not None else None,
                model=model, input_tokens=int(input_tokens or 0), output_tokens=int(output_tokens or 0),
                prev_hash=prev, hash="",
            )
            ev.hash = compute_hash(prev, hash_fields(ev))
            s.add(ev)
        return True
    except Exception as exc:
        AUDIT_FAILURES["count"] += 1
        log.warning("audit write failed (%s): %s", event_type, exc)
        return False


def upsert_incident(run_id, **fields):
    try:
        now = datetime.utcnow()
        with session_scope() as s:
            row = s.get(Incident, run_id)
            if row is None:
                row = Incident(run_id=run_id, created_at=now, updated_at=now)
                s.add(row)
            for key, value in fields.items():
                if value is not None:
                    setattr(row, key, str(value)[:100])
            row.updated_at = now
        return True
    except Exception as exc:
        AUDIT_FAILURES["count"] += 1
        log.warning("incident upsert failed: %s", exc)
        return False


def _event_dict(r):
    return {
        "seq": r.seq, "ts": r.ts.isoformat(), "event_type": r.event_type, "agent": r.agent,
        "ok": bool(r.ok), "summary": r.summary, "payload": r.payload, "latency_ms": r.latency_ms,
        "model": r.model, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
    }


def get_timeline(run_id):
    with session_scope() as s:
        rows = s.query(AuditEvent).filter(AuditEvent.run_id == run_id).order_by(AuditEvent.seq).all()
        return [_event_dict(r) for r in rows]


def get_incident(run_id):
    with session_scope() as s:
        row = s.get(Incident, run_id)
        if row is None:
            return None
        return {"run_id": row.run_id, "alert_id": row.alert_id, "environment": row.environment,
                "priority": row.priority, "status": row.status, "user_role": row.user_role,
                "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def list_incidents(limit=10, status=None):
    with session_scope() as s:
        q = s.query(Incident)
        if status:
            q = q.filter(Incident.status == status)
        rows = q.order_by(Incident.updated_at.desc()).limit(limit).all()
        return [{"run_id": r.run_id, "priority": r.priority, "environment": r.environment,
                 "status": r.status, "updated_at": r.updated_at.isoformat()} for r in rows]


def usage_summary(run_id):
    """Tokens come only from llm_call rows, latency only from agent_step rows, so nothing is counted twice."""
    result = {"total_input_tokens": 0, "total_output_tokens": 0, "llm_calls": 0, "by_agent": {}}
    for e in get_timeline(run_id):
        agent = e["agent"] or "-"
        slot = result["by_agent"].setdefault(agent, {"latency_ms": 0, "input_tokens": 0, "output_tokens": 0})
        if e["event_type"] == "llm_call":
            result["llm_calls"] += 1
            result["total_input_tokens"] += e["input_tokens"]
            result["total_output_tokens"] += e["output_tokens"]
            slot["input_tokens"] += e["input_tokens"]
            slot["output_tokens"] += e["output_tokens"]
        elif e["event_type"] == "agent_step":
            slot["latency_ms"] += e["latency_ms"] or 0
    return result


def verify_chain(run_id):
    """Returns (True, None) if intact, else (False, seq of the first bad or out-of-place event)."""
    with session_scope() as s:
        rows = s.query(AuditEvent).filter(AuditEvent.run_id == run_id).order_by(AuditEvent.seq).all()
        prev, expected = GENESIS, 1
        for r in rows:
            if r.seq != expected or r.prev_hash != prev or r.hash != compute_hash(prev, hash_fields(r)):
                return False, r.seq
            prev, expected = r.hash, expected + 1
    return True, None