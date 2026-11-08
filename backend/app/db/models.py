"""Normalized financial ledger + investigation + action schema.

Money is stored as integer minor units (BIGINT) with an ISO-4217 currency column. Never floats.
JSONB is used only for raw provider payloads and flexible evidence/tool results.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


DATA_ORIGINS = ("SANDBOX_LIVE", "SYNTHETIC", "WEBHOOK_VERIFIED", "RECONCILED_GET")
ORIGIN_CHECK = "origin IN ('SANDBOX_LIVE','SYNTHETIC','WEBHOOK_VERIFIED','RECONCILED_GET')"


class PayPalEvent(TimestampMixin, Base):
    """Raw provider events (webhooks or GET reconciliations). Dedup key = provider event id."""

    __tablename__ = "paypal_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    provider_event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False)  # WEBHOOK | RECONCILIATION | BOOTSTRAP
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)  # VERIFIED | UNVERIFIED | N/A
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    processing_status: Mapped[str] = mapped_column(String(24), nullable=False, default="APPLIED")
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Capture(TimestampMixin, Base):
    __tablename__ = "captures"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_capture_amount_positive"),
        CheckConstraint("refunded_minor >= 0 AND refunded_minor <= amount_minor", name="ck_capture_refund_bounds"),
        CheckConstraint(ORIGIN_CHECK, name="ck_capture_origin"),
        Index("ix_captures_captured_at", "captured_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    provider_capture_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(64))
    merchant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="demo-merchant")
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refunded_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    status_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # analytic dimensions
    product_sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_category: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    fulfillment_partner: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    buyer_memo: Mapped[str | None] = mapped_column(Text)  # UNTRUSTED free text
    origin: Mapped[str] = mapped_column(String(24), nullable=False)
    funding_source: Mapped[str | None] = mapped_column(String(16))  # card | paypal (from the PayPal order)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNVERIFIED")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciliation_flag: Mapped[str | None] = mapped_column(String(64))
    refunds: Mapped[list[Refund]] = relationship(back_populates="capture")


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_refund_amount_positive"),
        CheckConstraint(ORIGIN_CHECK, name="ck_refund_origin"),
        Index("ix_refunds_refunded_at", "refunded_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    provider_refund_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    capture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("captures.id"), nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    refunded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origin: Mapped[str] = mapped_column(String(24), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNVERIFIED")
    capture: Mapped[Capture] = relationship(back_populates="refunds")


class LedgerEntry(TimestampMixin, Base):
    """Append-only double-entry style ledger. One row per financial movement, unique per source reference."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("source_ref", "entry_type", name="uq_ledger_source_entry"),
        CheckConstraint("amount_minor <> 0", name="ck_ledger_nonzero"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False)  # CAPTURE | REFUND
    capture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("captures.id"), nullable=False, index=True)
    refund_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("refunds.id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)  # signed: refunds negative
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(64), nullable=False)  # provider id
    provenance_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("paypal_events.id"))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Incident(TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (UniqueConstraint("detector", "window_start", "window_end", name="uq_incident_window"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    detector: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)  # detector's own numbers (deterministic)
    root_cause_identified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvestigationRun(TimestampMixin, Base):
    __tablename__ = "investigation_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # AI | BASELINE
    model: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RUNNING")
    tool_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    trace: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # hypotheses / reasoning steps
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentToolCall(TimestampMixin, Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (UniqueConstraint("investigation_id", "query_id", name="uq_tool_query_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_runs.id"), nullable=False,
                                                        index=True)
    query_id: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. Q3, unique within the run
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(48), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # OK | REJECTED | ERROR
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), nullable=False, index=True)
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_runs.id"), nullable=False,
                                                        unique=True)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    observed_anomaly: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    uncertainty: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)
    root_cause_dimension: Mapped[str | None] = mapped_column(String(48))
    root_cause_value: Mapped[str | None] = mapped_column(String(64))
    recommended_action: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EvidenceRecord(TimestampMixin, Base):
    """One quantitative claim, checked against the tool result it cites."""

    __tablename__ = "evidence_records"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("findings.id"), nullable=False, index=True)
    tool_call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_tool_calls.id"))
    query_id: Mapped[str] = mapped_column(String(16), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    metric_path: Mapped[str] = mapped_column(String(200), nullable=False)
    claimed_value: Mapped[str] = mapped_column(String(64), nullable=False)
    source_value: Mapped[str | None] = mapped_column(String(64))
    verification: Mapped[str] = mapped_column(String(24), nullable=False)  # VERIFIED | UNSUPPORTED | CAUSE_VERIFIED | NOT_CAUSE_VERIFIED | CONTRADICTED | UNRESOLVED
    reason: Mapped[str | None] = mapped_column(Text)


class RemediationCase(TimestampMixin, Base):
    """A concrete customer complaint tied to one capture. A refund needs one; a refund-rate spike alone never counts."""

    __tablename__ = "remediation_cases"
    __table_args__ = (CheckConstraint("requested_minor > 0", name="ck_case_requested_positive"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    case_ref: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), nullable=False, index=True)
    capture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("captures.id"), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    customer_statement: Mapped[str] = mapped_column(Text, nullable=False)  # UNTRUSTED
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")


class ActionProposal(TimestampMixin, Base):
    __tablename__ = "action_proposals"
    __table_args__ = (
        CheckConstraint("amount_minor IS NULL OR amount_minor > 0", name="ck_proposal_amount_positive"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), nullable=False, index=True)
    finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("findings.id"))
    remediation_case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("remediation_cases.id"))
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_capture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("captures.id"))
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_by: Mapped[str] = mapped_column(String(32), nullable=False)  # AI | OPERATOR | ATTACKER_TEST
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PROPOSED")
    details_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    policy_result: Mapped[dict | None] = mapped_column(JSONB)


class ApprovalDecision(TimestampMixin, Base):
    __tablename__ = "approval_decisions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("action_proposals.id"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # APPROVED | REJECTED
    approver: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_details_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class FinancialExecution(TimestampMixin, Base):
    """Single-use execution claim: unique proposal_id makes a second concurrent execute fail at the DB."""

    __tablename__ = "financial_executions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("action_proposals.id"), nullable=False, unique=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_decisions.id"), nullable=False,
                                                   unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    # CLAIMED | SUBMITTED | VERIFIED | UNVERIFIED | FAILED
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(64))
    provider_status: Mapped[str | None] = mapped_column(String(32))
    request_payload: Mapped[dict | None] = mapped_column(JSONB)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    verification_payload: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("action_proposals.id"))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
