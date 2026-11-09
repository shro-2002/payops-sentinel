"""Incident Impact Engine: deterministic cohort exposure for each suspected driver.

The cohort of a driver is every capture in the incident window that matches its slice. Every figure is computed from
the ledger in integer minor units, per currency and per data origin, and carries a `basis` label:

  ACTUAL PAYPAL DATA   rows that came from real PayPal sandbox objects (origin SANDBOX_LIVE)
  SYNTHETIC HISTORY    generated analytical history (origin SYNTHETIC), never presented as real transactions
  SCENARIO ESTIMATE    a counterfactual (excess refunds over the comparison rate): an estimate, not a measurement

Captured value is exposure, never loss. Nothing here forecasts savings.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Capture, Incident, Refund, RemediationCase
from app.investigator.hypotheses import COUNTED_REFUND_STATUSES, windows
from app.money import to_str

BASIS = {"SANDBOX_LIVE": "ACTUAL PAYPAL DATA", "SYNTHETIC": "SYNTHETIC HISTORY"}
REFUNDABLE_STATUSES = ("COMPLETED", "PARTIALLY_REFUNDED")


def _money(minor: int, currency: str) -> dict:
    return {"minor": int(minor), "value": to_str(int(minor), currency), "currency": currency}


def _cohort(s: Session, start: datetime, end: datetime, dim: str, value: str) -> list[Capture]:
    return list(s.scalars(select(Capture).where(Capture.captured_at >= start, Capture.captured_at < end,
                                                getattr(Capture, dim) == value)))


def _group(caps: list[Capture], refunds_in_window: dict, open_cases: set) -> dict:
    """Totals for one (origin, currency) group of cohort captures."""
    cur = caps[0].currency
    refunded = [c for c in caps if refunds_in_window.get(c.id)]
    customers = {c.customer_ref for c in caps if c.customer_ref}
    reasons: dict[str, int] = defaultdict(int)
    for c in refunded:
        for r in refunds_in_window[c.id]:
            reasons[r.reason_code or "UNKNOWN"] += 1
    return {
        "basis": BASIS.get(caps[0].origin, caps[0].origin),
        "currency": cur,
        "transactions": len(caps),
        "customers": len(customers) if customers else None,  # None, not 0, when no identifiers exist
        "captured_value": _money(sum(c.amount_minor for c in caps), cur),
        "refunded_transactions": len(refunded),
        "refunded_in_window": _money(sum(r.amount_minor for c in refunded for r in refunds_in_window[c.id]), cur),
        "remaining_refundable": _money(sum(c.amount_minor - c.refunded_minor for c in caps
                                           if c.status in REFUNDABLE_STATUSES), cur),
        "unrefunded_transactions": len(caps) - len(refunded),
        "unrefunded_customers": (len({c.customer_ref for c in caps if c.customer_ref and c not in refunded})
                                 if customers else None),
        "open_customer_cases": sum(c.id in open_cases for c in caps),
        "refund_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
    }


def cohort_impact(s: Session, inc: Incident, dim: str, value: str, comparison_rate: float | None) -> dict:
    (start, end), _ = windows(inc)
    caps = _cohort(s, start, end, dim, value)
    ids = [c.id for c in caps]
    refunds_in_window: dict = defaultdict(list)
    if ids:
        for r in s.scalars(select(Refund).where(Refund.capture_id.in_(ids), Refund.refunded_at >= start,
                                                Refund.refunded_at < end,
                                                Refund.status.in_(COUNTED_REFUND_STATUSES))):
            refunds_in_window[r.capture_id].append(r)
    open_cases = set(s.scalars(select(RemediationCase.capture_id).where(
        RemediationCase.capture_id.in_(ids), RemediationCase.status == "OPEN"))) if ids else set()
    groups: dict[tuple[str, str], list[Capture]] = defaultdict(list)
    for c in caps:
        groups[(c.origin, c.currency)].append(c)
    by_group = [_group(g, refunds_in_window, open_cases) for _, g in sorted(groups.items())]
    estimate = _excess_estimate(caps, refunds_in_window, comparison_rate)
    refunded_ids = {cid for cid, rs in refunds_in_window.items() if rs}
    unrefunded_customers = {c.customer_ref for c in caps if c.customer_ref and c.id not in refunded_ids}
    return {"driver": {"dimension": dim, "value": value}, "window": {"start": start.isoformat(),
                                                                       "end": end.isoformat()},
            "groups": by_group, "excess_estimate": estimate,
            "unrefunded_customers_total": len(unrefunded_customers) if any(c.customer_ref for c in caps) else None,
            "summary": _summary(dim, value, by_group, estimate)}


def _excess_estimate(caps: list[Capture], refunds: dict, comparison_rate: float | None) -> list[dict]:
    """Refunds above what the rest of the window's refund rate would predict, per currency. A SCENARIO ESTIMATE."""
    if comparison_rate is None:
        return []
    out = []
    for cur in sorted({c.currency for c in caps}):
        cc = [c for c in caps if c.currency == cur]
        refunded = [c for c in cc if refunds.get(c.id)]
        expected = len(cc) * comparison_rate
        excess = max(len(refunded) - expected, 0.0)
        avg = sum(r.amount_minor for c in refunded for r in refunds[c.id]) // len(refunded) if refunded else 0
        origins = {o: sum(c.origin == o for c in cc) for o in sorted({c.origin for c in cc})}
        out.append({"basis": "SCENARIO ESTIMATE", "currency": cur, "refunds_observed": len(refunded),
                    "computed_over": {BASIS.get(o, o): n for o, n in origins.items()},
                    "refunds_expected_at_comparison_rate": round(expected, 1),
                    "comparison_rate": comparison_rate, "excess_refunds": round(excess, 1),
                    "excess_refund_value": _money(round(excess * avg), cur),
                    "note": "counterfactual at the rest-of-window refund rate; not a measured loss"})
    return out


def _summary(dim: str, value: str, groups: list[dict], estimate: list[dict]) -> str:
    if not groups:
        return f"No captures in the window match {dim}={value}."
    parts = []
    for g in groups:
        who = f" from {g['customers']} customers" if g["customers"] else ""
        parts.append(f"{g['transactions']} transactions{who} ({g['basis'].lower()}) carry "
                     f"{g['captured_value']['value']} {g['currency']} of captured value; "
                     f"{g['refunded_in_window']['value']} {g['currency']} was refunded in the window and "
                     f"{g['remaining_refundable']['value']} {g['currency']} remains refundable")
    text = f"Suspected affected cohort {dim}={value}: " + "; ".join(parts) + "."
    for e in estimate:
        text += (f" Estimated excess over the comparison rate: {e['excess_refunds']} refunds "
                 f"(~{e['excess_refund_value']['value']} {e['currency']}, scenario estimate).")
    return text
