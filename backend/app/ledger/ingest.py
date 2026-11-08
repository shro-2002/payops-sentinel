"""Idempotent ingestion of PayPal captures/refunds/events into the ledger.

Guarantees:
- Duplicate provider ids (capture, refund, event) never create a second financial row (DB unique + ON CONFLICT).
- Status never regresses on out-of-order delivery (monotonic status_rank).
- Unverified webhooks are stored for audit but never mutate financial state.
- A provider state that conflicts with the ledger is flagged for reconciliation, not silently overwritten.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Capture, LedgerEntry, PayPalEvent, Refund
from app.money import to_minor

# Higher rank = later in the lifecycle. Same-rank updates are idempotent no-ops.
CAPTURE_STATUS_RANK = {"PENDING": 0, "COMPLETED": 1, "PARTIALLY_REFUNDED": 2, "REFUNDED": 3, "DECLINED": 3,
                       "FAILED": 3}


@dataclass(frozen=True)
class CaptureDims:
    product_sku: str = "unknown"
    product_category: str = "unknown"
    region: str = "unknown"
    channel: str = "unknown"
    fulfillment_partner: str = "unknown"
    customer_ref: str = "unknown"
    buyer_memo: str | None = None


def _parse_ts(value: str | None) -> datetime:
    if not value or not isinstance(value, str):
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def upsert_capture(s: Session, payload: dict, *, dims: CaptureDims, origin: str, order_id: str | None = None,
                   verified: bool = False, funding_source: str | None = None) -> Capture:
    """Insert a capture from a PayPal capture object, or advance an existing one. Never regress."""
    status = payload["status"]
    currency = payload["amount"]["currency_code"]
    amount_minor = to_minor(payload["amount"]["value"], currency)
    when = _parse_ts(payload.get("create_time"))
    stmt = insert(Capture).values(
        id=uuid.uuid4(), provider_capture_id=payload["id"], provider_order_id=order_id,
        amount_minor=amount_minor, currency=currency, status=status,
        status_rank=CAPTURE_STATUS_RANK.get(status, 0), captured_at=when, status_updated_at=_parse_ts(
            payload.get("update_time")), product_sku=dims.product_sku, product_category=dims.product_category,
        region=dims.region, channel=dims.channel, fulfillment_partner=dims.fulfillment_partner,
        customer_ref=dims.customer_ref, buyer_memo=dims.buyer_memo, origin=origin, funding_source=funding_source,
        verification_status="VERIFIED" if verified else "UNVERIFIED",
        last_verified_at=datetime.now(timezone.utc) if verified else None,
    ).on_conflict_do_nothing(index_elements=["provider_capture_id"])
    s.execute(stmt)
    cap = s.scalars(select(Capture).where(Capture.provider_capture_id == payload["id"]).with_for_update().execution_options(populate_existing=True)).one()
    if cap.amount_minor != amount_minor or cap.currency != currency:
        cap.reconciliation_flag = "AMOUNT_MISMATCH_WITH_PROVIDER"
    apply_capture_status(s, cap, status, _parse_ts(payload.get("update_time")), verified=verified)
    _ensure_ledger(s, "CAPTURE", cap, None, amount_minor, payload["id"], when)
    return cap


def apply_capture_status(s: Session, cap: Capture, status: str, when: datetime, *, verified: bool) -> None:
    rank = CAPTURE_STATUS_RANK.get(status)
    if rank is None:
        cap.reconciliation_flag = f"UNKNOWN_PROVIDER_STATUS:{status}"[:64]
        return
    if rank > cap.status_rank:
        cap.status, cap.status_rank, cap.status_updated_at = status, rank, when
    elif rank < cap.status_rank and verified:
        # Provider (authoritative, verified) reports an EARLIER state than the ledger: do not regress, flag it.
        cap.reconciliation_flag = f"PROVIDER_REPORTS_{status}_LEDGER_{cap.status}"[:64]
    if verified:
        cap.verification_status, cap.last_verified_at = "VERIFIED", datetime.now(timezone.utc)


def upsert_refund(s: Session, payload: dict, *, capture: Capture, reason_code: str, origin: str,
                  verified: bool = False) -> Refund:
    currency = payload["amount"]["currency_code"]
    amount_minor = to_minor(payload["amount"]["value"], currency)
    if currency != capture.currency:
        raise ValueError("refund currency differs from capture currency")
    when = _parse_ts(payload.get("create_time"))
    s.execute(insert(Refund).values(
        id=uuid.uuid4(), provider_refund_id=payload["id"], capture_id=capture.id, amount_minor=amount_minor,
        currency=currency, status=payload["status"], reason_code=reason_code, refunded_at=when, origin=origin,
        verification_status="VERIFIED" if verified else "UNVERIFIED",
    ).on_conflict_do_nothing(index_elements=["provider_refund_id"]))
    ref = s.scalars(select(Refund).where(Refund.provider_refund_id == payload["id"])).one()
    if verified:
        ref.status, ref.verification_status = payload["status"], "VERIFIED"
    _ensure_ledger(s, "REFUND", capture, ref.id, -amount_minor, payload["id"], when)
    _recompute_refunded(s, capture)
    return ref


def _recompute_refunded(s: Session, cap: Capture) -> None:
    s.flush()
    total = s.scalar(select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
        Refund.capture_id == cap.id, Refund.status.in_(("COMPLETED", "PENDING"))))
    if total > cap.amount_minor:
        cap.reconciliation_flag = "REFUNDS_EXCEED_CAPTURE"
        return
    cap.refunded_minor = int(total)
    target = "REFUNDED" if total == cap.amount_minor else ("PARTIALLY_REFUNDED" if total else cap.status)
    apply_capture_status(s, cap, target, datetime.now(timezone.utc), verified=False)


def _ensure_ledger(s: Session, entry_type: str, cap: Capture, refund_id, amount_minor: int, source_ref: str,
                   when: datetime, event_id=None) -> None:
    s.execute(insert(LedgerEntry).values(
        id=uuid.uuid4(), entry_type=entry_type, capture_id=cap.id, refund_id=refund_id, amount_minor=amount_minor,
        currency=cap.currency, source_ref=source_ref, provenance_event_id=event_id, effective_at=when,
    ).on_conflict_do_nothing(constraint="uq_ledger_source_entry"))


def ingest_event(s: Session, event: dict, *, source: str, verified: bool) -> tuple[PayPalEvent, bool]:
    """Store a provider event once. Returns (row, is_new). Only VERIFIED events may touch the ledger."""
    resource = event.get("resource") or {}
    res = s.execute(insert(PayPalEvent).values(
        id=uuid.uuid4(), provider_event_id=event["id"], event_type=event.get("event_type", "UNKNOWN"),
        resource_type=event.get("resource_type"), resource_id=resource.get("id"), source=source,
        verification_status="VERIFIED" if verified else "UNVERIFIED",
        source_timestamp=_parse_ts(event.get("create_time")) if event.get("create_time") else None,
        correlation_id=resource.get("custom_id") or resource.get("invoice_id"),
        processing_status="PENDING" if verified else "IGNORED_UNVERIFIED", raw_payload=event,
    ).on_conflict_do_nothing(index_elements=["provider_event_id"]).returning(PayPalEvent.id))
    new_id = res.scalar()
    row = s.scalars(select(PayPalEvent).where(PayPalEvent.provider_event_id == event["id"]).with_for_update().execution_options(populate_existing=True)).one()
    if new_id is None and verified and row.verification_status != "VERIFIED":
        # An unsigned POST may have stored this id first; the genuine signed event replaces it and is applied.
        s.add(AuditEvent(actor="system", event_type="UNVERIFIED_EVENT_SUPERSEDED",
                         details={"provider_event_id": event["id"]}))
        row.verification_status, row.processing_status, row.raw_payload = "VERIFIED", "PENDING", event
        row.event_type, row.source = event.get("event_type", "UNKNOWN"), source
        row.resource_id = resource.get("id")
        _apply_verified_event(s, row, event)
        return row, True
    if new_id is None and verified and row.processing_status == "NEEDS_RECONCILIATION":
        # Redelivery of an event that arrived before its parent capture: try again now.
        _apply_verified_event(s, row, event)
        return row, True
    if new_id is None:
        s.add(AuditEvent(actor="system", event_type="DUPLICATE_PROVIDER_EVENT",
                         details={"provider_event_id": event["id"]}))
        return row, False
    if not verified:
        s.add(AuditEvent(actor="system", event_type="UNVERIFIED_EVENT_REJECTED",
                         details={"provider_event_id": event["id"], "event_type": row.event_type}))
        return row, True
    _apply_verified_event(s, row, event)
    return row, True


def _apply_verified_event(s: Session, row: PayPalEvent, event: dict) -> None:
    resource = event.get("resource") or {}
    etype = row.event_type
    if etype in REFUND_RESOURCE_EVENTS:
        _apply_refund_event(s, row, resource)
    elif etype.startswith("PAYMENT.CAPTURE."):
        cap = s.scalars(select(Capture).where(Capture.provider_capture_id == resource.get("id"))).first()
        if cap is None:
            upsert_capture(s, resource, dims=CaptureDims(), origin="WEBHOOK_VERIFIED", verified=True)
        else:
            apply_capture_status(s, cap, resource.get("status", "UNKNOWN"), _parse_ts(resource.get("update_time")),
                                 verified=True)
        row.processing_status = "APPLIED"
    else:
        row.processing_status = "IGNORED_TYPE"


# PayPal sends a REFUND resource with these capture events (REVERSED = refund initiated by PayPal, e.g. chargeback).
REFUND_RESOURCE_EVENTS = {"PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"}


def _apply_refund_event(s: Session, row: PayPalEvent, resource: dict) -> None:
    cap_id = _parent_capture_id(resource)
    cap = s.scalars(select(Capture).where(Capture.provider_capture_id == cap_id)).first() if cap_id else None
    if cap is None:
        row.processing_status = "NEEDS_RECONCILIATION"
        return
    if resource.get("status") not in ("COMPLETED", "PENDING"):
        row.processing_status = "IGNORED_REFUND_STATUS"
        return
    reason = "PROVIDER_REVERSAL" if row.event_type == "PAYMENT.CAPTURE.REVERSED" else "PROVIDER_EVENT"
    upsert_refund(s, resource, capture=cap, reason_code=reason, origin="WEBHOOK_VERIFIED", verified=True)
    from app.actions.service import confirm_from_webhook  # local import: ledger must not depend on actions at load
    confirm_from_webhook(s, resource, row.provider_event_id)
    row.processing_status = "APPLIED"


def _parent_capture_id(refund_resource: dict) -> str | None:
    for link in refund_resource.get("links", []):
        href = link.get("href", "")
        if link.get("rel") == "up" and "/captures/" in href:
            return href.rstrip("/").split("/captures/")[-1]
    return None


def order_funding_source(order: dict) -> str | None:
    """PayPal Orders v2 puts exactly one key under payment_source: 'card', 'paypal', 'venmo', ..."""
    keys = list((order.get("payment_source") or {}).keys())
    return keys[0][:16] if keys else None
