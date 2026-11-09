"""Export the latest COMPLETED live Claude investigation as a replay fixture for judge mode (REPLAY_LLM=1).

Usage: python -m scripts.export_replay   -> backend/fixtures/replays/investigation.json
"""

import json
from collections import defaultdict

from sqlalchemy import select

from app.db.models import EvidenceRecord, Finding, InvestigationRun
from app.db.session import SessionLocal
from app.investigator.agent import REPLAY_DIR


def main() -> None:
    with SessionLocal() as s:
        run = s.scalars(select(InvestigationRun).where(InvestigationRun.mode == "AI", InvestigationRun.status ==
                                                       "COMPLETED", InvestigationRun.model.like("claude-%"))
                        .order_by(InvestigationRun.created_at.desc())).first()
        if run is None:
            raise SystemExit("no completed live Claude investigation to export")
        f = s.scalars(select(Finding).where(Finding.investigation_id == run.id)).one()
        turns = defaultdict(list)
        for t in run.trace:
            if t.get("step") == "tool":
                turns[t["turn"]].append({"name": t["tool"], "args": t["args"]})
        extra = {t["step"]: t["value"] for t in run.trace if t.get("step") in ("secondary_causes", "hypotheses")}
        evidence = s.scalars(select(EvidenceRecord).where(EvidenceRecord.finding_id == f.id)).all()
        final = {"hypotheses_considered": extra.get("hypotheses", []), "hypothesis": f.hypothesis,
                 "observed_anomaly": f.observed_anomaly, "explanation": f.explanation, "uncertainty": f.uncertainty,
                 "confidence": f.confidence,
                 "root_cause": {"dimension": f.root_cause_dimension, "value": f.root_cause_value}
                 if f.root_cause_dimension else None,
                 "secondary_causes": extra.get("secondary_causes", []), "recommended_action": f.recommended_action,
                 "claims": [{"statement": e.statement, "query_id": e.query_id, "metric_path": e.metric_path,
                             "value": e.claimed_value} for e in evidence if e.verification in ("VERIFIED", "UNSUPPORTED")],
                 "cause_claims": []}
        out = {"model": run.model, "recorded_at": run.created_at.isoformat(), "source_investigation_id": str(run.id),
               "note": "Recorded live Claude investigation. Replayed tool calls run against the current database; "
                       "claims are re-verified on replay.", "turns": [turns[k] for k in sorted(turns)], "final": final}
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    (REPLAY_DIR / "investigation.json").write_text(json.dumps(out, indent=2))
    print({"exported": str(run.id), "turns": len(out["turns"]), "claims": len(final["claims"]),
           "cause_claims": len(final["cause_claims"])})


if __name__ == "__main__":
    main()
