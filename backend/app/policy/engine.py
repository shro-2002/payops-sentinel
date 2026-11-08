"""Deterministic financial policy engine. Independent of the model: it re-derives every fact from the database.

Every check is recorded (pass/fail + detail) so the UI can show exactly why an action was allowed or blocked.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ActionProposal, Capture, FinancialExecution, Incident, RemediationCase

ALLOWED_ACTIONS = {"NO_ACTION", "MANUAL_REVIEW", "PARTIAL_REFUND"}
MONEY_ACTIONS = {"PARTIAL_REFUND"}
REFUNDABLE_ORIGINS = {"SANDBOX_LIVE", "WEBHOOK_VERIFIED", "RECONCILED_GET"}
REFUNDABLE_STATUSES = {"COMPLETED", "PARTIALLY_REFUNDED"}
MERCHANT_ID = "demo-merchant"


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def details_hash(action_type: str, provider_capture_id: str | None, amount_minor: int | None, currency: str | None,
                 case_ref: str | None) -> str:
    """Approval binds to this hash. Any change to type, target, amount, currency or case invalidates it."""
    canon = json.dumps({"a": action_type, "t": provider_capture_id, "m": amount_minor, "c": currency, "r": case_ref},
                       sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def proposal_hash(s: Session, p: ActionProposal) -> str:
    cap = s.get(Capture, p.target_capture_id) if p.target_capture_id else None
    case = s.get(RemediationCase, p.remediation_case_id) if p.remediation_case_id else None
    return details_hash(p.action_type, cap.provider_capture_id if cap else None, p.amount_minor, p.currency,
                        case.case_ref if case else None)


def evaluate(s: Session, p: ActionProposal, *, provider_status: str | None = None) -> tuple[bool, list[Check]]:
    """provider_* are supplied at execution time from a fresh PayPal GET (re-validation)."""
    checks: list[Check] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append(Check(name, bool(ok), detail))

    add("action_type_allowed", p.action_type in ALLOWED_ACTIONS, f"action_type={p.action_type}")
    if p.action_type not in MONEY_ACTIONS:
        add("no_money_movement", p.amount_minor is None and p.target_capture_id is None,
            "non-financial action must not carry an amount or target")
        return all(c.passed for c in checks), checks

    cfg = get_settings()
    inc = s.get(Incident, p.incident_id)
    cap = s.get(Capture, p.target_capture_id) if p.target_capture_id else None
    case = s.get(RemediationCase, p.remediation_case_id) if p.remediation_case_id else None
    add("incident_open", inc is not None and inc.status not in ("RESOLVED", "CLOSED"),
        f"incident status={inc.status if inc else 'missing'}")
    add("target_exists", cap is not None, "target capture found" if cap else "target capture not in ledger")
    add("remediation_case_linked", case is not None and case.status == "OPEN",
        "open remediation case required; a refund-rate spike alone is not a refund reason")
    if cap is None or case is None:
        add("evaluation_complete", False, "cannot evaluate money checks without target and case")
        return False, checks
    add("case_matches_target", case.capture_id == cap.id, "case must concern the same capture")
    add("case_in_incident_scope", case.incident_id == p.incident_id, "case must belong to this incident")
    add("capture_ownership", cap.merchant_id == MERCHANT_ID, f"merchant={cap.merchant_id}")
    add("real_provider_capture", cap.origin in REFUNDABLE_ORIGINS,
        f"origin={cap.origin} (synthetic history is never refundable)")
    status = provider_status or cap.status
    add("capture_refundable_status", status in REFUNDABLE_STATUSES, f"status={status}")
    add("currency_matches", p.currency == cap.currency == case.currency,
        f"proposal={p.currency} capture={cap.currency} case={case.currency}")
    amount = p.amount_minor or 0
    remaining = cap.amount_minor - cap.refunded_minor
    add("amount_positive", amount > 0, f"amount_minor={amount}")
    add("within_remaining_refundable", amount <= remaining, f"amount={amount} remaining={remaining}")
    add("within_case_request", amount <= case.requested_minor, f"amount={amount} requested={case.requested_minor}")
    add("within_policy_cap", amount <= cfg.refund_cap_minor, f"amount={amount} cap={cfg.refund_cap_minor}")
    prior = s.scalar(select(func.count()).select_from(FinancialExecution).join(
        ActionProposal, FinancialExecution.proposal_id == ActionProposal.id).where(
        ActionProposal.remediation_case_id == case.id, ActionProposal.id != p.id,
        FinancialExecution.status.in_(("CLAIMED", "SUBMITTED", "VERIFIED", "UNVERIFIED"))))
    add("no_prior_refund_for_case", prior == 0, f"prior executions for case={prior}")
    add("reason_present", bool(p.reason and p.reason.strip()), "reason required")
    return all(c.passed for c in checks), checks


def as_json(passed: bool, checks: list[Check]) -> dict:
    return {"passed": passed, "checks": [asdict(c) for c in checks]}
