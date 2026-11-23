from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Incident(Base):
    __tablename__ = "incidents"

    run_id = Column(String(64), primary_key=True)
    alert_id = Column(String(100))
    environment = Column(String(50))
    priority = Column(String(10))
    status = Column(String(50))
    user_role = Column(String(50))
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_audit_run_seq"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    ts = Column(DateTime, nullable=False)
    event_type = Column(String(30), nullable=False)   # agent_step / llm_call / tool_call / approval_requested / approval
    agent = Column(String(30))
    ok = Column(Boolean, nullable=False)
    summary = Column(String(500), nullable=False)
    payload = Column(JSON, nullable=False)
    latency_ms = Column(Integer)
    model = Column(String(100))
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    prev_hash = Column(String(64), nullable=False)
    hash = Column(String(64), nullable=False)