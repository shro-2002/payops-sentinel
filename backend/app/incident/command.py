"""Incident command view: what happened, which explanation survived, who is affected, what to do, what was done.

Three outcomes are tracked separately, because they are different business facts:
  investigation_status          what the evidence supports (never "root cause proven")
  operational_response_status   typed follow-ups for people (carrier, quality, listing) - no fake integrations
  paypal_execution_status       money actually moved at PayPal, and whether PayPal confirmed it
An incident is never resolved because one customer's refund succeeded.

Recommendation statuses: PROPOSED | APPROVED | MANUAL_FOLLOW_UP_REQUIRED | EXECUTED | VERIFIED | UNRESOLVED, plus
IN_PROGRESS / FAILED for a refund case whose execution is claimed or failed.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActionProposal, Capture, FinancialExecution, Incident, RemediationCase
from app.incident.impact import cohort_impact
from app.investigator.hypotheses import compete
from app.money import to_str

MANUAL = "MANUAL_FOLLOW_UP_REQUIRED"

# Driver dimension -> the follow-up a payments-ops team would actually own. Wording only; nothing is automated.
PLAYBOOK = {
    "fulfillment_partner": ("CARRIER_INVESTIGATION", "Open a carrier investigation with {v}: request scan and "
                            "delivery-confirmation data for the affected shipments"),
    "region": ("REGIONAL_LOGISTICS_REVIEW", "Review last-mile logistics in {v} with the carriers serving it"),
    "product_sku": ("QUALITY_REVIEW", "Quality review of {v}; consider a temporary inventory hold until the batch is "
                    "inspected"),
    "product_category": ("QUALITY_REVIEW", "Quality review across {v} products"),
    "channel": ("LISTING_REVIEW", "Audit the {v} channel: listing content, fulfilment mapping and integration errors"),
}


def _driver_recs(drivers: list[dict], impacts: dict) -> list[dict]:
    recs = []
    for d in drivers:
        dim, v = d["dimension"], d["value"]
        kind, text = PLAYBOOK[dim]
        imp = impacts.get((dim, v), {})
        groups = imp.get("groups", [])
        unrefunded = sum(g["unrefunded_transactions"] for g in groups)
        customers = imp.get("unrefunded_customers_total")
        recs.append({"type": kind, "status": MANUAL, "driver": d, "action": text.format(v=v),
                     "why": f"{dim}={v} survived every falsification challenge (suspected contributing factor)",
                     "automated": False})
        if unrefunded:
            who = f"{customers} customers" if customers else "the affected customers"
            recs.append({"type": "CUSTOMER_COMMUNICATION", "status": "PROPOSED", "driver": d, "automated": False,
                         "action": f"Prioritise proactive outreach to {who} in the {dim}={v} cohort "
                                   f"({unrefunded} transactions not yet refunded)",
                         "why": "customers in a supported cohort are likely to raise claims next"})
    return recs


def _case_recs(s: Session, inc: Incident) -> list[dict]:
    """Individual customer cases, linked to the human-approved PayPal refund flow."""
    out = []
    for case in s.scalars(select(RemediationCase).where(RemediationCase.incident_id == inc.id)):
        cap = s.get(Capture, case.capture_id)
        props = s.scalars(select(ActionProposal).where(ActionProposal.remediation_case_id == case.id)
                          .order_by(ActionProposal.created_at.desc())).all()
        ex = next((e for p in props for e in s.scalars(select(FinancialExecution)
                                                        .where(FinancialExecution.proposal_id == p.id))), None)
        if ex and ex.status == "VERIFIED":
            status = "VERIFIED"
        elif ex and ex.status in ("SUBMITTED", "UNVERIFIED"):
            status = "EXECUTED"  # sent to PayPal, not yet confirmed by a read-back
        elif ex and ex.status == "FAILED":
            status = "FAILED"
        elif ex and ex.status == "CLAIMED":
            status = "IN_PROGRESS"  # execution claimed; nothing confirmed as sent
        elif any(p.status == "APPROVED" for p in props):
            status = "APPROVED"
        else:
            status = "PROPOSED"
        out.append({"type": "INDIVIDUAL_REFUND_CASE", "status": status, "automated": False,
                    "case_ref": case.case_ref, "capture_id": cap.provider_capture_id if cap else None,
                    "capture_origin": cap.origin if cap else None, "requested": to_str(case.requested_minor,
                                                                                      case.currency),
                    "currency": case.currency,
                    "action": f"Case {case.case_ref}: refund decision through policy, human approval and PayPal",
                    "why": "a concrete customer complaint on one capture; never justified by the spike alone",
                    "paypal": ex and {"refund_id": ex.provider_refund_id, "execution_status": ex.status,
                                      "provider_status": ex.provider_status,
                                      "verified_by_get": ex.status == "VERIFIED"}})
    return out


def _paypal_status(cases: list[dict]) -> dict:
    counts = {k: sum(c["status"] == k for c in cases)
              for k in ("PROPOSED", "APPROVED", "IN_PROGRESS", "EXECUTED", "VERIFIED", "FAILED")}
    if not cases:
        label = "NO_FINANCIAL_ACTION"
    elif counts["FAILED"]:
        label = "EXECUTION_FAILED_NEEDS_REVIEW"
    elif counts["EXECUTED"] or counts["IN_PROGRESS"]:
        label = "EXECUTED_AWAITING_VERIFICATION"
    elif counts["VERIFIED"] == len(cases):
        label = "ALL_CASES_VERIFIED"
    elif counts["VERIFIED"]:
        label = "PARTIALLY_EXECUTED"
    else:
        label = "PENDING_APPROVAL"
    return {"status": label, "cases": counts}


def build_command(s: Session, inc: Incident) -> dict:
    report = compete(s, inc)
    by_key = {(t["hypothesis"]["dimension"], t["hypothesis"]["value"]): t for t in report["tests"]}
    drivers = report["supported"]
    impacts = {(d["dimension"], d["value"]): cohort_impact(
        s, inc, d["dimension"], d["value"], by_key[(d["dimension"], d["value"])]["slice"]["comparison"]["rate"])
        for d in drivers}
    recs = _driver_recs(drivers, impacts)
    if report["decision"] == "ABSTAIN_INDISTINGUISHABLE":
        seen = {frozenset({(u["hypothesis"]["dimension"], u["hypothesis"]["value"]),
                           ((u["indistinguishable_from"] or {}).get("dimension"),
                            (u["indistinguishable_from"] or {}).get("value"))}) for u in report["unresolved"]}
        pairs = "; ".join(" vs ".join(f"{d}={v}" for d, v in sorted(p)) for p in seen)
        recs.append({"type": "ESCALATE_TO_ANALYST", "status": "UNRESOLVED", "automated": False,
                     "action": f"Escalate: the data cannot separate {pairs}. Collect data that breaks the tie "
                               f"(e.g. ship a sample of one SKU via another carrier) before acting",
                     "why": "no corrective action is recommended without a supported driver"})
    elif not drivers:
        recs.append({"type": "ESCALATE_TO_ANALYST", "status": "UNRESOLVED", "automated": False,
                     "action": "Escalate for analyst review: no hypothesis survived falsification",
                     "why": "no corrective action is recommended without a supported driver"})
    cases = _case_recs(s, inc)
    investigation = {"SUSPECTED_DRIVERS_FOUND": "SUSPECTED_DRIVERS_FOUND",
                     "ABSTAIN_INDISTINGUISHABLE": "ABSTAINED_INDISTINGUISHABLE",
                     "ABSTAIN_NO_SUPPORTED_DRIVER": "ABSTAINED_NO_SUPPORTED_DRIVER"}[report["decision"]]
    manual_open = sum(r["status"] in (MANUAL, "PROPOSED") for r in recs)
    return {
        "incident_id": str(inc.id),
        "statuses": {
            "investigation": investigation,
            "operational_response": (f"{manual_open} FOLLOW_UPS_OPEN" if manual_open else
                                     "ESCALATED" if any(r["status"] == "UNRESOLVED" for r in recs) else "NONE"),
            "paypal_execution": _paypal_status(cases),
            "incident": "OPEN" if inc.status not in ("RESOLVED", "CLOSED") else inc.status,
            "note": "Individual refunds settle individual customer cases; they do not resolve the incident.",
        },
        "challenger": report,
        "impact": list(impacts.values()),
        "response_plan": recs + cases,
    }
