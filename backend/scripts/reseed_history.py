"""Swap the demo world's SYNTHETIC history for another scenario, keeping every real sandbox row untouched.

Real PayPal sandbox captures (origin SANDBOX_LIVE), their events and the remediation cases stay as they are; no
PayPal call is made. Synthetic captures/refunds/ledger rows and investigation/proposal state are removed (audit events are kept, and a SYNTHETIC_HISTORY_RESEEDED event records the swap), the
scenario is seeded into the same incident window, and the incident's detector numbers are recomputed in place (same
incident id, so cases stay linked). Refuses to run if any financial execution exists.

Usage: python -m scripts.reseed_history demo_carrier_and_batch [--seed N]
"""

import argparse

from sqlalchemy import delete, select, text

from app.db.models import (ActionProposal, AgentToolCall, ApprovalDecision, AuditEvent, Capture, EvidenceRecord,
                           FinancialExecution, Finding, Incident, InvestigationRun, LedgerEntry, Refund)
from app.db.session import SessionLocal
from app.detection.refund_rate import evaluate
from app.ledger.synthetic import ADVERSARIAL, SCENARIOS, seed


def main(name: str, rng_seed: int) -> None:
    sc = ADVERSARIAL.get(name) or SCENARIOS[name]
    with SessionLocal() as s:
        if s.scalar(select(FinancialExecution.id).limit(1)):
            raise SystemExit("refusing: a financial execution exists; reseeding would orphan real money records")
        if s.scalar(select(ActionProposal.id).limit(1)):
            raise SystemExit("refusing: proposals exist (their audit events reference them); start from a fresh world")
        inc = s.scalars(select(Incident)).one()
        old_title = inc.title
        for model in (EvidenceRecord, Finding, AgentToolCall, InvestigationRun, ApprovalDecision, ActionProposal):
            s.execute(delete(model))
        syn = select(Capture.id).where(Capture.origin == "SYNTHETIC")
        s.execute(delete(LedgerEntry).where(LedgerEntry.capture_id.in_(syn)))
        s.execute(delete(Refund).where(Refund.capture_id.in_(syn)))
        s.execute(delete(Capture).where(Capture.origin == "SYNTHETIC"))
        seed(s, sc, inc.window_end, rng_seed=rng_seed)
        ev = evaluate(s, inc.window_end)
        if not ev["fired"]:
            raise SystemExit(f"detector does not fire on {name}; nothing changed")
        inc.metrics = {k: v for k, v in ev.items() if k not in ("window_start", "window_end")}
        inc.title = (f"Refund rate {ev['current']['rate']:.1%} vs {ev['baseline']['rate']:.1%} baseline "
                     f"({ev['current']['refunds']} refunds / {ev['current']['captures']} captures)")
        s.add(AuditEvent(actor="reseed_history", event_type="SYNTHETIC_HISTORY_RESEEDED", incident_id=inc.id,
                         details={"scenario": name, "seed": rng_seed, "old_title": old_title, "new_title": inc.title,
                                  "note": "synthetic rows replaced; SANDBOX_LIVE rows and cases untouched"}))
        inc.status, inc.root_cause_identified = "OPEN", False
        s.commit()
        print(inc.id, inc.title, s.execute(text("select origin, count(*) from captures group by origin")).all())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    main(a.scenario, a.seed)
