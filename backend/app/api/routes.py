"""HTTP API. Routers stay thin; behaviour lives in ledger/detection/investigator/policy/actions.

Read endpoints serve the console. Every write endpoint requires the server-side operator bearer token; with no token
configured, writes are disabled (safe default for any public deployment).
"""

from __future__ import annotations

import hmac
import re
import json
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.actions import service
from app.actions.service import ActionError
from app.config import get_settings
from app.db.models import (ActionProposal, AgentToolCall, ApprovalDecision, AuditEvent, Capture, EvidenceRecord,
                           FinancialExecution, Finding, Incident, InvestigationRun, PayPalEvent, Refund,
                           RemediationCase)
from app.db.session import get_db
from app.detection.refund_rate import run_detector
from app.integrations.paypal.client import PayPalClient
from app.investigator.agent import run_ai_investigation, run_baseline_investigation
from app.actions.drafting import draft_proposal
from app.ledger.ingest import ingest_event
from app.money import to_str

router = APIRouter(prefix="/api/v1")
REPORTS = Path(__file__).resolve().parents[3] / "reports"


@lru_cache
def paypal_client() -> PayPalClient:
    c = get_settings()
    return PayPalClient(c.paypal_client_id, c.paypal_client_secret, c.paypal_base_url)


def operator(authorization: str = Header(default=""), x_operator: str = Header(default="")) -> str:
    token = get_settings().operator_token
    if not token:
        raise HTTPException(503, detail={"code": "WRITES_DISABLED", "message": "operator token not configured"})
    presented = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(presented.encode(), token.encode()):
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "operator token required"})
    # Identity is asserted by the console proxy, which authenticated the human; only trusted with a valid token.
    name = x_operator if re.fullmatch(r"[A-Za-z0-9._-]{1,32}", x_operator or "") else "console"
    return f"operator:{name.lower()}"


def _err(e: ActionError):
    return HTTPException(e.status, detail={"code": e.code, "message": str(e)})


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


# ---- serializers ----------------------------------------------------------------------------------
def ser_incident(i: Incident) -> dict:
    return {"id": str(i.id), "detector": i.detector, "severity": i.severity, "status": i.status, "title": i.title,
            "window_start": _iso(i.window_start), "window_end": _iso(i.window_end), "metrics": i.metrics,
            "root_cause_identified": i.root_cause_identified, "created_at": _iso(i.created_at)}


def ser_capture(c: Capture) -> dict:
    return {"id": c.provider_capture_id, "order_id": c.provider_order_id, "amount": to_str(c.amount_minor, c.currency),
            "refunded": to_str(c.refunded_minor, c.currency), "currency": c.currency, "status": c.status,
            "captured_at": _iso(c.captured_at), "product_sku": c.product_sku, "product_category": c.product_category,
            "region": c.region, "channel": c.channel, "fulfillment_partner": c.fulfillment_partner,
            "customer_ref": c.customer_ref, "origin": c.origin, "verification_status": c.verification_status,
            "reconciliation_flag": c.reconciliation_flag, "buyer_memo_untrusted": c.buyer_memo,
            "source_label": "PayPal sandbox" if c.origin in REAL_ORIGINS else "synthetic",
            "paypal_id": c.provider_capture_id if c.origin in REAL_ORIGINS else None,
            "funding_source": c.funding_source}


REAL_ORIGINS = ("SANDBOX_LIVE", "WEBHOOK_VERIFIED", "RECONCILED_GET")


def ser_tool_call(t: AgentToolCall, with_result: bool = True) -> dict:
    out = {"id": str(t.id), "query_id": t.query_id, "seq": t.seq, "tool": t.tool_name, "arguments": t.arguments,
           "status": t.status, "error": t.error, "duration_ms": t.duration_ms}
    return out | ({"result": t.result} if with_result else {})


def ser_proposal(s: Session, p: ActionProposal) -> dict:
    cap = s.get(Capture, p.target_capture_id) if p.target_capture_id else None
    case = s.get(RemediationCase, p.remediation_case_id) if p.remediation_case_id else None
    ex = s.scalars(select(FinancialExecution).where(FinancialExecution.proposal_id == p.id)).first()
    approvals = s.scalars(select(ApprovalDecision).where(ApprovalDecision.proposal_id == p.id)
                          .order_by(ApprovalDecision.created_at)).all()
    return {"id": str(p.id), "incident_id": str(p.incident_id), "action_type": p.action_type, "status": p.status,
            "target_capture_id": cap.provider_capture_id if cap else None,
            "amount": to_str(p.amount_minor, p.currency) if p.amount_minor and p.currency else None,
            "currency": p.currency, "case_ref": case.case_ref if case else None, "reason": p.reason,
            "proposed_by": p.proposed_by, "details_hash": p.details_hash, "policy": p.policy_result,
            "created_at": _iso(p.created_at),
            "approvals": [{"decision": a.decision, "approver": a.approver, "expires_at": _iso(a.expires_at),
                           "consumed_at": _iso(a.consumed_at)} for a in approvals],
            "execution": ex and {"id": str(ex.id), "status": ex.status, "provider_refund_id": ex.provider_refund_id,
                                 "provider_status": ex.provider_status, "error": ex.error,
                                 "verified_at": _iso(ex.finished_at),
                                 "verified_at_paypal": ex.status == "VERIFIED" and bool(ex.verification_payload),
                                 "verified_via": (ex.verification_payload or {}).get("via")}}


def ser_case(s: Session, c: RemediationCase) -> dict:
    cap = s.get(Capture, c.capture_id)
    return {"case_ref": c.case_ref, "incident_id": str(c.incident_id), "capture_id": cap.provider_capture_id,
            "issue_type": c.issue_type, "requested": to_str(c.requested_minor, c.currency), "currency": c.currency,
            "customer_statement_untrusted": c.customer_statement, "status": c.status}


def ser_investigation(s: Session, r: InvestigationRun) -> dict:
    calls = s.scalars(select(AgentToolCall).where(AgentToolCall.investigation_id == r.id)
                      .order_by(AgentToolCall.seq)).all()
    f = s.scalars(select(Finding).where(Finding.investigation_id == r.id)).first()
    ev = s.scalars(select(EvidenceRecord).where(EvidenceRecord.finding_id == f.id)).all() if f else []
    return {"id": str(r.id), "incident_id": str(r.incident_id), "mode": r.mode, "model": r.model, "status": r.status,
            "tool_calls_used": r.tool_calls_used, "max_tool_calls": r.max_tool_calls, "latency_ms": r.latency_ms,
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "error": r.error, "trace": r.trace,
            "created_at": _iso(r.created_at), "tool_calls": [ser_tool_call(c) for c in calls],
            "finding": f and {
                "id": str(f.id), "hypothesis": f.hypothesis, "observed_anomaly": f.observed_anomaly,
                "explanation": f.explanation, "uncertainty": f.uncertainty, "confidence": f.confidence,
                "root_cause": {"dimension": f.root_cause_dimension, "value": f.root_cause_value}
                if f.root_cause_dimension else None,
                "recommended_action": f.recommended_action, "verified_claims": f.verified_claim_count,
                "unsupported_claims": f.unsupported_claim_count,
                "evidence": [{"id": str(e.id), "query_id": e.query_id, "tool_call_id": str(e.tool_call_id)
                              if e.tool_call_id else None, "statement": e.statement, "metric_path": e.metric_path,
                              "claimed_value": e.claimed_value, "source_value": e.source_value,
                              "verification": e.verification, "reason": e.reason} for e in ev]}}


# ---- read endpoints -------------------------------------------------------------------------------
@router.get("/incidents", dependencies=[Depends(operator)])
def list_incidents(db: Session = Depends(get_db)):
    return {"data": [ser_incident(i) for i in db.scalars(select(Incident).order_by(Incident.created_at.desc()))]}


@router.get("/incidents/{incident_id}", dependencies=[Depends(operator)])
def get_incident(incident_id: uuid.UUID, db: Session = Depends(get_db)):
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "incident not found"})
    runs = db.scalars(select(InvestigationRun).where(InvestigationRun.incident_id == inc.id)
                      .order_by(InvestigationRun.created_at.desc())).all()
    props = db.scalars(select(ActionProposal).where(ActionProposal.incident_id == inc.id)
                       .order_by(ActionProposal.created_at.desc())).all()
    cases = db.scalars(select(RemediationCase).where(RemediationCase.incident_id == inc.id)).all()
    audit = db.scalars(select(AuditEvent).where(AuditEvent.incident_id == inc.id).order_by(AuditEvent.id)).all()
    return {"data": ser_incident(inc) | {
        "investigations": [ser_investigation(db, r) for r in runs],
        "proposals": [ser_proposal(db, p) for p in props],
        "remediation_cases": [ser_case(db, c) for c in cases],
        "audit": [{"id": a.id, "at": _iso(a.occurred_at), "actor": a.actor, "event": a.event_type,
                   "proposal_id": str(a.proposal_id) if a.proposal_id else None, "details": a.details}
                  for a in audit]}}


@router.get("/tool-calls/{call_id}", dependencies=[Depends(operator)])
def get_tool_call(call_id: uuid.UUID, db: Session = Depends(get_db)):
    t = db.get(AgentToolCall, call_id)
    if t is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "tool call not found"})
    return {"data": ser_tool_call(t)}


@router.get("/evidence/{evidence_id}/records", dependencies=[Depends(operator)])
def evidence_records(evidence_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """Drill-through: the ledger rows behind ONE claim, using the cited call's own window and filters."""
    e = db.get(EvidenceRecord, evidence_id)
    if e is None or e.tool_call_id is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "evidence not found"})
    call = db.get(AgentToolCall, e.tool_call_id)
    if call.status != "OK":
        raise HTTPException(404, detail={"code": "NO_RECORDS", "message": "cited call did not succeed"})
    inc = db.get(Incident, db.get(InvestigationRun, call.investigation_id).incident_id)
    rows, scope = drill_rows(db, inc, call.tool_name, call.arguments or {}, e.metric_path, limit)
    return {"data": {"evidence_id": str(e.id), "query_id": e.query_id, "scope": scope,
                     "tool_result": call.result, "records": [ser_capture(c) for c in rows]}}


def drill_rows(db: Session, inc: Incident, tool: str, args: dict, path: str, limit: int):
    from app.investigator.tools import DIMENSIONS, _windows
    parts = path.split("/")
    if tool == "get_transaction":
        cap = db.scalars(select(Capture).where(Capture.provider_capture_id == args.get("capture_id"))).first()
        return ([cap] if cap else []), {"capture_id": args.get("capture_id")}
    window = "baseline" if args.get("window") == "baseline" or parts[0] == "baseline" else "current"
    start, end = _windows(inc)[window]
    filters = {}
    if args.get("dimension") in DIMENSIONS and args.get("value"):
        filters[args["dimension"]] = args["value"]
    if parts[0] == "by_value" and len(parts) > 1:
        dim = args.get("by") if tool == "cross_slice" else args.get("dimension")
        if dim in DIMENSIONS:
            filters[dim] = parts[1]
    leaf = parts[-1]
    refund_view = parts[0] == "by_reason" or "refund" in leaf or leaf in ("rate", "refunded_minor")
    if refund_view:  # refunds are counted by refund time; show the captures behind those refunds
        q = (select(Capture).join(Refund, Refund.capture_id == Capture.id)
             .where(Refund.refunded_at >= start, Refund.refunded_at < end))
        if parts[0] == "by_reason" and len(parts) > 1:
            q = q.where(Refund.reason_code == parts[1])
            filters["reason_code"] = parts[1]
    else:
        q = select(Capture).where(Capture.captured_at >= start, Capture.captured_at < end)
    for dim, value in filters.items():
        if dim in DIMENSIONS:
            q = q.where(DIMENSIONS[dim] == value)
    rows = db.scalars(q.order_by(Capture.captured_at.desc()).limit(limit)).unique().all()
    return rows, {"window": window, "start": _iso(start), "end": _iso(end), "filters": filters,
                  "view": "refunds_in_window" if refund_view else "captures_in_window"}


@router.get("/transactions", dependencies=[Depends(operator)])
def list_transactions(limit: int = Query(500, ge=1, le=2000), origin: str | None = None, db: Session = Depends(get_db)):
    q = select(Capture).order_by(Capture.captured_at.desc()).limit(min(max(limit, 1), 2000))
    if origin:
        q = q.where(Capture.origin == origin)
    return {"data": [ser_capture(c) for c in db.scalars(q)]}


@router.get("/metrics/refund-trend", dependencies=[Depends(operator)])
def refund_trend(hours: int = Query(192, ge=1, le=720), db: Session = Depends(get_db)):
    """Hourly buckets of captures/refunds for the trend chart (both computed from persisted rows)."""
    end = db.scalar(select(func.max(Capture.captured_at))) or datetime.now(timezone.utc)
    start = end - timedelta(hours=min(hours, 24 * 30))
    bucket = func.date_trunc("hour", Capture.captured_at)
    caps = dict(db.execute(select(bucket, func.count()).where(Capture.captured_at >= start).group_by(bucket)).all())
    rb = func.date_trunc("hour", Refund.refunded_at)
    refs = dict(db.execute(select(rb, func.count()).where(Refund.refunded_at >= start).group_by(rb)).all())
    keys = sorted(set(caps) | set(refs))
    return {"data": [{"hour": k.isoformat(), "captures": caps.get(k, 0), "refunds": refs.get(k, 0)} for k in keys]}


@router.get("/proposals/{proposal_id}", dependencies=[Depends(operator)])
def get_proposal(proposal_id: uuid.UUID, db: Session = Depends(get_db)):
    p = db.get(ActionProposal, proposal_id)
    if p is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "proposal not found"})
    return {"data": ser_proposal(db, p)}


@router.get("/events", dependencies=[Depends(operator)])
def list_events(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.scalars(select(PayPalEvent).order_by(PayPalEvent.ingested_at.desc()).limit(min(limit, 500))).all()
    return {"data": [{"id": e.provider_event_id, "type": e.event_type, "resource_id": e.resource_id,
                      "source": e.source, "verification": e.verification_status, "processing": e.processing_status,
                      "ingested_at": _iso(e.ingested_at)} for e in rows]}


@router.get("/evaluation", dependencies=[Depends(operator)])
def evaluation():
    f = REPORTS / "evaluation-results.json"
    if not f.exists():
        return {"data": None}
    return {"data": json.loads(f.read_text())}


@router.get("/config")
def public_config():
    c = get_settings()
    return {"data": {"writes_enabled": bool(c.operator_token), "refund_cap": to_str(c.refund_cap_minor, "USD"),
                     "llm_model": c.anthropic_model if c.llm_provider == "anthropic" else c.llm_model, "max_tool_calls": c.max_tool_calls, "paypal_env": "sandbox",
                     "webhook_verification": "configured" if c.paypal_webhook_id else "not_configured"}}


# ---- write endpoints ------------------------------------------------------------------------------
class InvestigateIn(BaseModel):
    mode: Literal["AI", "BASELINE"] = "AI"


class ProposalIn(BaseModel):
    incident_id: uuid.UUID
    action_type: Literal["NO_ACTION", "MANUAL_REVIEW", "PARTIAL_REFUND"]
    reason: str = Field(min_length=3, max_length=2000)
    target_capture_id: str | None = Field(default=None, max_length=64)
    amount: str | None = Field(default=None, pattern=r"^[0-9]{1,7}(\.[0-9]{1,2})?$")
    currency: Literal["USD"] | None = None
    case_ref: str | None = Field(default=None, max_length=32)


class DecisionIn(BaseModel):
    approve: bool
    details_hash: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=500)


@router.post("/detection/run")
def detection_run(db: Session = Depends(get_db), actor: str = Depends(operator)):
    inc = run_detector(db)
    db.commit()
    return {"data": ser_incident(inc) if inc else None}


@router.post("/incidents/{incident_id}/investigations")
def investigate(incident_id: uuid.UUID, body: InvestigateIn, db: Session = Depends(get_db),
                actor: str = Depends(operator)):
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "incident not found"})
    run = run_ai_investigation(db, inc) if body.mode == "AI" else run_baseline_investigation(db, inc)
    db.commit()
    return {"data": ser_investigation(db, run)}


@router.post("/remediation-cases/{case_ref}/draft-proposal")
def draft(case_ref: str, db: Session = Depends(get_db), actor: str = Depends(operator)):
    case = db.scalars(select(RemediationCase).where(RemediationCase.case_ref == case_ref)).first()
    if case is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "case not found"})
    p, info = draft_proposal(db, case)
    db.commit()
    return {"data": {"proposal": ser_proposal(db, p) if p else None, "drafting": info}}


@router.post("/proposals", status_code=201)
def create_proposal(body: ProposalIn, db: Session = Depends(get_db), actor: str = Depends(operator)):
    try:
        p = service.propose(db, incident_id=body.incident_id, action_type=body.action_type, reason=body.reason,
                            proposed_by=actor, target_provider_capture_id=body.target_capture_id,
                            amount=body.amount, currency=body.currency, case_ref=body.case_ref)
    except ActionError as e:
        raise _err(e) from e
    db.commit()
    return {"data": ser_proposal(db, p)}


@router.post("/proposals/{proposal_id}/decision")
def decide(proposal_id: uuid.UUID, body: DecisionIn, db: Session = Depends(get_db), actor: str = Depends(operator)):
    try:
        service.decide(db, proposal_id, approver=actor, approve=body.approve, details_hash=body.details_hash,
                       note=body.note)
    except ActionError as e:
        db.rollback()
        raise _err(e) from e
    db.commit()
    return {"data": ser_proposal(db, db.get(ActionProposal, proposal_id))}


@router.post("/proposals/{proposal_id}/execute")
def execute(proposal_id: uuid.UUID, db: Session = Depends(get_db), actor: str = Depends(operator)):
    try:
        service.execute(db, proposal_id, actor=actor, paypal=paypal_client())
    except ActionError as e:
        raise _err(e) from e
    db.expire_all()
    return {"data": ser_proposal(db, db.get(ActionProposal, proposal_id))}


@router.post("/executions/{execution_id}/verify")
def reverify(execution_id: uuid.UUID, db: Session = Depends(get_db), actor: str = Depends(operator)):
    ex = db.get(FinancialExecution, execution_id)
    if ex is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "execution not found"})
    if ex.status == "VERIFIED":
        return {"data": ser_proposal(db, db.get(ActionProposal, ex.proposal_id))}
    if ex.status == "CLAIMED":
        # CLAIMED is committed BEFORE submission and SUBMITTED is committed before the PayPal call, so a CLAIMED row
        # was provably never sent: safe to close it out as FAILED (no money moved).
        try:
            service.abandon_unsubmitted(db, ex.id)
        except ActionError as e:
            raise _err(e) from e
        return {"data": ser_proposal(db, db.get(ActionProposal, ex.proposal_id))}
    if ex.status not in ("UNVERIFIED", "SUBMITTED"):
        raise HTTPException(409, detail={"code": "NOT_VERIFIABLE", "message": f"execution is {ex.status}"})
    service.verify(db, ex.id, paypal=paypal_client())
    return {"data": ser_proposal(db, db.get(ActionProposal, ex.proposal_id))}


class WebhookEventIn(BaseModel):
    """Shape check only; trust still comes solely from PayPal signature verification."""
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    event_type: str = Field(default="UNKNOWN", max_length=64)
    resource_type: str | None = Field(default=None, max_length=32)
    create_time: str | None = Field(default=None, max_length=40)
    resource: dict = Field(default_factory=dict)


def _handle_webhook(event: dict, headers: dict) -> dict:
    webhook_id = get_settings().paypal_webhook_id
    verified = False
    if webhook_id and all(headers.get(h) for h in ("paypal-transmission-id", "paypal-transmission-sig")):
        try:
            verified = paypal_client().verify_webhook_signature(headers=headers, event=event, webhook_id=webhook_id)
        except Exception:  # verification outage => unverified, never trusted
            verified = False
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        row, new = ingest_event(db, event, source="WEBHOOK", verified=verified)
        db.commit()
        return {"accepted": True, "verified": verified, "duplicate": not new, "processing": row.processing_status}


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request):
    """Public by necessity. Trust comes only from PayPal's verify-webhook-signature answer, never from the body."""
    from starlette.concurrency import run_in_threadpool
    raw = await request.body()
    if len(raw) > 256_000:
        raise HTTPException(413, detail={"code": "TOO_LARGE", "message": "payload too large"})
    try:
        parsed = WebhookEventIn.model_validate_json(raw)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "BAD_EVENT", "message": "invalid event"}) from e
    event = json.loads(raw)
    event["resource"] = parsed.resource
    headers = {k.lower(): v for k, v in request.headers.items()}
    # Blocking PayPal + DB work runs in the threadpool so it never stalls the event loop.
    return {"data": await run_in_threadpool(_handle_webhook, event, headers)}
