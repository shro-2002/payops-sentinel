"""Server-enforced action lifecycle.

PROPOSED -> POLICY_PASSED | POLICY_REJECTED
POLICY_PASSED -> APPROVED | REJECTED            (human, bound to details hash, expires)
APPROVED -> EXECUTING -> EXECUTED | EXECUTION_UNVERIFIED | EXECUTION_FAILED

The executor: claims a single-use execution row (unique per proposal AND per approval) inside a row lock, re-checks
the approval hash/expiry, re-validates against a fresh PayPal GET, submits the refund with a STABLE idempotency key,
then verifies by GET. Uncertain outcomes stay UNVERIFIED; they are never retried under a new key.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (ActionProposal, ApprovalDecision, AuditEvent, Capture, FinancialExecution, Incident,
                           RemediationCase)
from app.integrations.paypal.client import PayPalClient, PayPalClientError, PayPalError
from app.ledger.ingest import apply_capture_status, upsert_refund
from app.money import to_minor, to_str
from app.policy import engine


class ActionError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.status = code, status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(s: Session, actor: str, event: str, p: ActionProposal | None, **details) -> None:
    s.add(AuditEvent(actor=actor, event_type=event, incident_id=p.incident_id if p else details.pop("incident_id", None),
                     proposal_id=p.id if p else None, details=details))


def propose(s: Session, *, incident_id: uuid.UUID, action_type: str, reason: str, proposed_by: str,
            target_provider_capture_id: str | None = None, amount: str | None = None, currency: str | None = None,
            case_ref: str | None = None, finding_id: uuid.UUID | None = None) -> ActionProposal:
    if s.get(Incident, incident_id) is None:
        raise ActionError("INCIDENT_NOT_FOUND", "incident not found", 404)
    cap = (s.scalars(select(Capture).where(Capture.provider_capture_id == target_provider_capture_id)).first()
           if target_provider_capture_id else None)
    case = (s.scalars(select(RemediationCase).where(RemediationCase.case_ref == case_ref)).first()
            if case_ref else None)
    try:
        amount_minor = to_minor(amount, currency) if amount is not None and currency else None
    except ValueError as e:
        raise ActionError("INVALID_AMOUNT", str(e), 422) from e
    if amount_minor is not None and amount_minor <= 0:
        raise ActionError("INVALID_AMOUNT", "amount must be positive", 422)
    p = ActionProposal(incident_id=incident_id, finding_id=finding_id, remediation_case_id=case.id if case else None,
                       action_type=action_type, target_capture_id=cap.id if cap else None, amount_minor=amount_minor,
                       currency=currency, reason=reason[:2000], proposed_by=proposed_by, status="PROPOSED",
                       details_hash="pending", idempotency_key=f"payops-{uuid.uuid4()}")
    s.add(p)
    s.flush()
    p.details_hash = engine.proposal_hash(s, p)
    passed, checks = engine.evaluate(s, p)
    if target_provider_capture_id and cap is None:
        checks.insert(0, engine.Check("target_exists", False, f"unknown capture {target_provider_capture_id}"))
        passed = False
    if case_ref and case is None:
        checks.insert(0, engine.Check("remediation_case_linked", False, f"unknown case {case_ref}"))
        passed = False
    p.policy_result = engine.as_json(passed, checks)
    p.status = "POLICY_PASSED" if passed else "POLICY_REJECTED"
    _audit(s, proposed_by, "ACTION_PROPOSED", p, action_type=action_type, amount_minor=amount_minor,
           target=target_provider_capture_id, case_ref=case_ref)
    _audit(s, "policy", "POLICY_PASSED" if passed else "POLICY_VIOLATION", p,
           failed=[c.name for c in checks if not c.passed])
    return p


def decide(s: Session, proposal_id: uuid.UUID, *, approver: str, approve: bool, details_hash: str,
           note: str | None = None) -> ApprovalDecision:
    p = s.scalars(select(ActionProposal).where(ActionProposal.id == proposal_id).with_for_update().execution_options(populate_existing=True)).first()
    if p is None:
        raise ActionError("NOT_FOUND", "proposal not found", 404)
    if p.status != "POLICY_PASSED":
        raise ActionError("NOT_APPROVABLE", f"proposal in state {p.status} cannot be decided")
    current = engine.proposal_hash(s, p)
    if details_hash != current or p.details_hash != current:
        raise ActionError("DETAILS_CHANGED", "approval must reference the exact current action details")
    is_ai_approver = approver.lower().startswith("ai")
    if approver.lower() == (p.proposed_by or "").lower():
        if not (get_settings().local_console and approver == "operator:local-operator"):
            raise ActionError("SELF_APPROVAL", "the proposer cannot approve their own action (four-eyes)", 403)
        # Dev-only single-identity console: allowed, but the waiver is recorded in the audit trail.
        _audit(s, approver, "FOUR_EYES_WAIVED_LOCAL_DEV", p)
    if is_ai_approver:
        raise ActionError("APPROVER_NOT_HUMAN", "AI cannot approve its own proposal", 403)
    d = ApprovalDecision(proposal_id=p.id, decision="APPROVED" if approve else "REJECTED", approver=approver,
                         approved_details_hash=current, note=note,
                         expires_at=_now() + timedelta(minutes=get_settings().approval_ttl_minutes))
    s.add(d)
    p.status = "APPROVED" if approve else "REJECTED"
    s.flush()
    _audit(s, approver, "ACTION_APPROVED" if approve else "ACTION_REJECTED", p, approval_id=str(d.id))
    return d


def _claim(s: Session, proposal_id: uuid.UUID, actor: str) -> tuple[ActionProposal, FinancialExecution]:
    p = s.scalars(select(ActionProposal).where(ActionProposal.id == proposal_id).with_for_update().execution_options(populate_existing=True)).first()
    if p is None:
        raise ActionError("NOT_FOUND", "proposal not found", 404)
    if p.action_type not in engine.MONEY_ACTIONS:
        raise ActionError("NOT_EXECUTABLE", "only money actions are executed")
    if p.status != "APPROVED":
        _audit(s, actor, "EXECUTION_REFUSED", p, reason=f"state {p.status}")
        s.commit()
        raise ActionError("NOT_APPROVED", f"proposal in state {p.status} cannot execute")
    d = s.scalars(select(ApprovalDecision).where(ApprovalDecision.proposal_id == p.id,
                                                 ApprovalDecision.decision == "APPROVED")
                  .order_by(ApprovalDecision.created_at.desc())).first()
    reasons = []
    if d is None:
        reasons.append("no approval")
    else:
        if d.consumed_at is not None:
            reasons.append("approval already used")
        if d.expires_at < _now():
            reasons.append("approval expired")
        if d.approved_details_hash != engine.proposal_hash(s, p):
            reasons.append("action details changed after approval")
    if reasons:
        p.status = "APPROVAL_INVALID"
        _audit(s, actor, "EXECUTION_REFUSED", p, reason="; ".join(reasons))
        s.commit()
        raise ActionError("APPROVAL_INVALID", "; ".join(reasons))
    ex = FinancialExecution(proposal_id=p.id, approval_id=d.id, status="CLAIMED", idempotency_key=p.idempotency_key)
    s.add(ex)
    d.consumed_at = _now()
    p.status = "EXECUTING"
    try:
        s.flush()
    except IntegrityError as e:
        s.rollback()
        raise ActionError("ALREADY_EXECUTED", "an execution already exists for this proposal") from e
    _audit(s, actor, "EXECUTION_CLAIMED", p, execution_id=str(ex.id))
    s.commit()
    return p, ex


def execute(s: Session, proposal_id: uuid.UUID, *, actor: str, paypal: PayPalClient) -> FinancialExecution:
    p, ex = _claim(s, proposal_id, actor)
    cap = s.get(Capture, p.target_capture_id)
    case = s.get(RemediationCase, p.remediation_case_id)
    # 1) re-validate against the provider right before moving money
    try:
        live = paypal.get_capture(cap.provider_capture_id).body
    except PayPalError as e:
        return _fail(s, p, ex, "PREFLIGHT_FAILED", f"could not confirm capture state: {e}", final="EXECUTION_FAILED")
    # The capture GET carries status, not a refunded total (verified live: no total_refunded_amount), so remaining
    # refundable comes from the ledger, and provider status catches full refunds made elsewhere.
    passed, checks = engine.evaluate(s, p, provider_status=live.get("status"))
    if not passed:
        p.policy_result = engine.as_json(passed, checks) | {"stage": "pre_execution_revalidation"}
        return _fail(s, p, ex, "REVALIDATION_FAILED", "policy failed on fresh provider state",
                     final="EXECUTION_FAILED", failed=[c.name for c in checks if not c.passed])
    # 2) submit with the stable idempotency key
    request = {"capture_id": cap.provider_capture_id, "amount": to_str(p.amount_minor, p.currency),
               "currency": p.currency, "invoice_id": case.case_ref}
    locked = s.scalars(select(FinancialExecution).where(FinancialExecution.id == ex.id).with_for_update().execution_options(populate_existing=True)).one()
    if locked.status != "CLAIMED":  # abandoned/closed concurrently: never submit
        s.commit()
        raise ActionError("CLAIM_LOST", f"execution is {locked.status}; not submitting")
    ex.request_payload, ex.status = request, "SUBMITTED"
    s.commit()
    try:
        resp = paypal.refund_capture(cap.provider_capture_id, amount=request["amount"], currency=p.currency,
                                     request_id=ex.idempotency_key, invoice_id=None,
                                     note_to_payer=f"Remediation {case.case_ref}")
    except PayPalClientError as e:
        ex.response_payload = {"status": e.status, "body": e.body}
        return _fail(s, p, ex, "PROVIDER_REJECTED", str(e), final="EXECUTION_FAILED")
    except PayPalError as e:
        # Outcome unknown. Do NOT retry with a new key. Leave UNVERIFIED for reconciliation (same key / GET).
        ex.status, ex.error = "UNVERIFIED", f"submission outcome unknown: {e}"
        p.status = "EXECUTION_UNVERIFIED"
        _audit(s, "executor", "EXECUTION_UNVERIFIED", p, error=ex.error)
        s.commit()
        return ex
    ex.response_payload, ex.provider_refund_id = resp.body, resp.body.get("id")
    ex.provider_status = resp.body.get("status")
    if get_settings().paypal_webhook_id:
        # Webhook mode: the signed PAYMENT.CAPTURE.REFUNDED event confirms it (confirm_from_webhook). GET read-back
        # via verify() stays available as the fallback if the event never arrives.
        _audit(s, "executor", "AWAITING_PROVIDER_WEBHOOK", p, refund_id=ex.provider_refund_id)
        s.commit()
        return ex
    s.commit()
    return verify(s, ex.id, paypal=paypal)


def confirm_from_webhook(s: Session, refund_resource: dict, event_id: str) -> FinancialExecution | None:
    """Called for a signature-VERIFIED refund event. Marks the matching execution VERIFIED (idempotent)."""
    ex = s.scalars(select(FinancialExecution).where(FinancialExecution.provider_refund_id == refund_resource.get("id"))
                   .with_for_update().execution_options(populate_existing=True)).first()
    if ex is None or ex.status == "VERIFIED":
        return ex
    p = s.get(ActionProposal, ex.proposal_id)
    amount = refund_resource.get("amount") or {}
    amount_ok = amount.get("value") == to_str(p.amount_minor, p.currency) and amount.get("currency_code") == p.currency
    if refund_resource.get("status") != "COMPLETED" or not amount_ok:
        ex.error = f"webhook refund state {refund_resource.get('status')} amount_ok={amount_ok}"
        _audit(s, "webhook", "EXECUTION_UNVERIFIED", p, error=ex.error, event_id=event_id)
        return ex
    ex.status, ex.provider_status, ex.finished_at = "VERIFIED", "COMPLETED", _now()
    ex.verification_payload = {"via": "paypal_webhook", "event_id": event_id, "resource": refund_resource}
    p.status = "EXECUTED"
    case = s.get(RemediationCase, p.remediation_case_id)
    if case:
        case.status = "RESOLVED"
    _audit(s, "webhook", "EXECUTION_VERIFIED", p, via="paypal_webhook", event_id=event_id,
           refund_id=ex.provider_refund_id, amount=amount)
    return ex


def verify(s: Session, execution_id: uuid.UUID, *, paypal: PayPalClient) -> FinancialExecution:
    """Confirm the refund at PayPal (GET) and only then write it to the ledger as VERIFIED."""
    ex = s.get(FinancialExecution, execution_id)
    if ex.status == "VERIFIED":
        return ex
    p = s.get(ActionProposal, ex.proposal_id)
    cap = s.get(Capture, p.target_capture_id)
    case = s.get(RemediationCase, p.remediation_case_id)
    if not ex.provider_refund_id:
        # Unknown outcome. PayPal returns the original refund for a replayed PayPal-Request-Id, but only within its
        # idempotency retention window, and only if the action is still within policy on fresh provider state.
        locked = s.scalars(select(FinancialExecution).where(FinancialExecution.id == ex.id).with_for_update()
                           .execution_options(populate_existing=True)).one()
        age = _now() - locked.created_at
        if age < REPLAY_MIN_AGE:
            raise ActionError("TOO_EARLY", "submission may still be in flight; retry in a minute")
        if age > REPLAY_MAX_AGE:
            locked.error = "replay window exceeded: reconcile manually in the PayPal dashboard"
            s.commit()
            return locked
        try:
            live_status = paypal.get_capture(cap.provider_capture_id).body.get("status")
        except PayPalError as e:
            locked.error = f"reconciliation pre-check failed: {e}"
            s.commit()
            return locked
        passed, checks = engine.evaluate(s, p, provider_status=live_status)
        if not passed:
            # Fail closed: never (re)submit outside policy. A human reconciles against the PayPal dashboard.
            locked.error = ("manual reconciliation required; replay blocked by policy: "
                            + ",".join(c.name for c in checks if not c.passed))
            s.commit()
            return locked
        try:  # replay with the SAME idempotency key returns the original refund if it was created
            resp = paypal.refund_capture(cap.provider_capture_id, amount=to_str(p.amount_minor, p.currency),
                                         currency=p.currency, request_id=ex.idempotency_key,
                                         note_to_payer=f"Remediation {case.case_ref}")
            ex.provider_refund_id = resp.body.get("id")
        except PayPalError as e:
            ex.error = f"reconciliation attempt failed: {e}"
            s.commit()
            return ex
    try:
        got = paypal.get_refund(ex.provider_refund_id).body
    except PayPalError as e:
        ex.status, ex.error, p.status = "UNVERIFIED", f"refund GET failed: {e}", "EXECUTION_UNVERIFIED"
        _audit(s, "executor", "EXECUTION_UNVERIFIED", p, error=ex.error)
        s.commit()
        return ex
    ex.verification_payload = got
    amount_ok = got.get("amount", {}).get("value") == to_str(p.amount_minor, p.currency) and \
        got.get("amount", {}).get("currency_code") == p.currency
    if got.get("status") in ("FAILED", "CANCELLED"):
        ex.verification_payload = got
        return _fail(s, p, ex, "PROVIDER_REFUND_FAILED", f"provider refund {got.get('status')}",
                     final="EXECUTION_FAILED")
    if got.get("status") == "COMPLETED" and amount_ok:
        upsert_refund(s, got, capture=cap, reason_code=case.issue_type, origin="SANDBOX_LIVE", verified=True)
        live = paypal.get_capture(cap.provider_capture_id).body
        apply_capture_status(s, cap, live.get("status", cap.status), _now(), verified=True)
        ex.status, ex.provider_status = "VERIFIED", got.get("status")
        ex.verification_payload = {"via": "paypal_get", "resource": got}
        ex.finished_at = _now()
        p.status = "EXECUTED"
        case.status = "RESOLVED"
        _audit(s, "executor", "EXECUTION_VERIFIED", p, refund_id=ex.provider_refund_id,
               provider_status=got.get("status"), amount=got.get("amount"))
    else:
        ex.status, p.status = "UNVERIFIED", "EXECUTION_UNVERIFIED"
        ex.error = f"provider refund state {got.get('status')} amount_ok={amount_ok}"
        _audit(s, "executor", "EXECUTION_UNVERIFIED", p, error=ex.error)
    s.commit()
    return ex


def _fail(s: Session, p: ActionProposal, ex: FinancialExecution, code: str, msg: str, *, final: str,
          **extra) -> FinancialExecution:
    ex.status, ex.error, ex.finished_at = "FAILED", f"{code}: {msg}"[:2000], _now()
    p.status = final
    _audit(s, "executor", "EXECUTION_FAILED", p, code=code, error=msg[:500], **extra)
    s.commit()
    return ex


ABANDON_AFTER = timedelta(minutes=10)
# Replay of an unknown-outcome refund is allowed only after the client timeout (no race with an in-flight
# execute()) and before the approval TTL ends (a human authorised this action for that long, not longer).
REPLAY_MIN_AGE = timedelta(seconds=60)
REPLAY_MAX_AGE = timedelta(minutes=get_settings().approval_ttl_minutes)


def abandon_unsubmitted(s: Session, execution_id: uuid.UUID, *, now: datetime | None = None) -> FinancialExecution:
    """Close a CLAIMED execution that never reached SUBMITTED. Row-locked against execute(), which re-checks
    CLAIMED under the same lock before submitting, and only allowed after a timeout so an in-flight execute()
    (still in pre-flight) is never cut off."""
    ex = s.scalars(select(FinancialExecution).where(FinancialExecution.id == execution_id).with_for_update().execution_options(populate_existing=True)).one()
    if ex.status != "CLAIMED":
        raise ActionError("NOT_ABANDONABLE", f"execution is {ex.status}")
    if (now or _now()) - ex.created_at < ABANDON_AFTER:
        raise ActionError("TOO_EARLY", "execution may still be in flight; retry after 10 minutes")
    p = s.get(ActionProposal, ex.proposal_id)
    return _fail(s, p, ex, "ABANDONED_BEFORE_SUBMISSION", "claim was never submitted to PayPal",
                 final="EXECUTION_FAILED")
