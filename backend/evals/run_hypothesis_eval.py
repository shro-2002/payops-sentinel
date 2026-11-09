"""Competing-hypothesis evaluation: does the investigator avoid false attributions on adversarial incidents?

Systems (all scored against the same planted ground truth):
  A  BASELINE    deterministic: largest share of excess across all dimensions (the prior best, 91/100 on easy cases)
  B  AI_V1       the original AI investigator (share-of-excess era prompt, no falsification tool)
  C  AI_FALSIFY  the competing-hypothesis AI investigator (falsification protocol + test_hypothesis tool)
  D  CHALLENGER  the deterministic falsification engine on its own (app.investigator.hypotheses.compete)

What each system CLAIMS is scored (root_cause + secondary causes); for B and C we also report what the server's
independent challenge confirmed. A and D run on 10 RNG seeds per scenario; B and C cost LLM quota, so they run only
with --ai-seeds N (N seeds per scenario per system) and every paid run is appended to the results file immediately.

Metrics: primary-driver accuracy (driver scenarios), multi-factor recall (two-cause scenarios), false-attribution rate
(any claimed driver outside the truth), decoy-hit rate, appropriate-abstention rate (indistinguishable / no anomaly),
inappropriate-abstention rate (driver scenarios), evidence-citation validity (AI), tool calls, latency, cost.

Usage: python -m evals.run_hypothesis_eval [--ai-seeds N] [--systems B,C] [--scenarios a,b]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from evals.run_eval import AS_OF, PRICE_PER_M, ROOT, SessionLocal, engine, reset  # noqa: F401 (sets eval DB)
from sqlalchemy import select

from app.db.models import Base, Finding, Incident
from app.detection.refund_rate import evaluate, run_detector
from app.investigator.agent import run_ai_investigation, run_baseline_investigation
from app.investigator.hypotheses import compete
from app.ledger.synthetic import ADVERSARIAL, SCENARIOS, seed

OUT = ROOT / "reports" / "hypothesis-eval-results.json"
DEV_SEEDS = range(1, 11)        # thresholds were calibrated while looking at these
HELDOUT_SEEDS = range(11, 41)   # never used for calibration; reported separately
DET_SEEDS = [*DEV_SEEDS, *HELDOUT_SEEDS]
SUITE = {k: v for k, v in ADVERSARIAL.items() if not k.startswith("demo_")} | {
    k: v for k, v in SCENARIOS.items() if v.truth}  # classic easy scenarios (90 captures) for regression


def _world(s, sc, rng_seed):
    seed(s, sc, AS_OF, rng_seed=rng_seed)
    inc = run_detector(s, AS_OF)
    if inc is None:  # no-anomaly world: investigate the window anyway to measure false attribution
        ev = evaluate(s, AS_OF)
        inc = Incident(detector="MANUAL", severity="P3", title="manual investigation, detector did not fire",
                       window_start=ev["window_start"], window_end=ev["window_end"],
                       metrics={k: v for k, v in ev.items() if k not in ("window_start", "window_end")})
        s.add(inc)
        s.flush()
    return inc


def score(sc, primary: tuple | None, claimed: set) -> dict:
    truth = set(sc.truth)
    canon = {sc.canonical(c) for c in claimed}
    abstained = not claimed
    out = {"claimed": sorted(claimed), "abstained": abstained,
           "false_attribution": bool(canon - truth) or (sc.expect_abstain and not abstained),
           "decoy_hit": bool(set(sc.decoys) & claimed)}
    if sc.expect_abstain:
        out["appropriate_abstention"] = abstained
    else:
        out["primary_correct"] = primary is not None and sc.canonical(primary) in truth
        out["recall"] = len(canon & truth) / len(truth)
        out["inappropriate_abstention"] = abstained
    return out


def _finding_claims(s, run) -> tuple[tuple | None, set, set]:
    f = s.scalars(select(Finding).where(Finding.investigation_id == run.id)).first()
    if f is None:
        return None, set(), set()
    primary = (f.root_cause_dimension, f.root_cause_value) if f.root_cause_dimension else None
    claimed = {primary} if primary else set()
    confirmed = set()
    for t in run.trace or []:
        if t.get("step") == "secondary_causes":
            claimed |= {(c["dimension"], c["value"]) for c in t["value"]}
        if t.get("step") == "driver_challenges":
            confirmed |= {(c["dimension"], c["value"]) for c in t["value"] if c["verdict"] == "ASSOCIATION_SUPPORTED"}
    return primary, claimed, confirmed


def run_deterministic(name, sc, rng_seed) -> list[dict]:
    rows = []
    reset()
    with SessionLocal() as s:
        inc = _world(s, sc, rng_seed)
        t0 = time.perf_counter()
        rep = compete(s, inc)
        ms = int((time.perf_counter() - t0) * 1000)
        claimed = {(h["dimension"], h["value"]) for h in rep["supported"]}
        primary = (rep["primary"]["dimension"], rep["primary"]["value"]) if rep["primary"] else None
        rows.append({"system": "D_CHALLENGER", "scenario": name, "seed": rng_seed, **score(sc, primary, claimed),
                     "tool_calls": len(rep["tests"]), "latency_ms": ms, "cost_usd": 0.0})
        run = run_baseline_investigation(s, inc)
        primary, claimed, _ = _finding_claims(s, run)
        rows.append({"system": "A_BASELINE", "scenario": name, "seed": rng_seed, **score(sc, primary, claimed),
                     "tool_calls": run.tool_calls_used, "latency_ms": run.latency_ms, "cost_usd": 0.0})
        s.rollback()
    return rows


def run_ai(name, sc, rng_seed, system) -> dict:
    protocol = {"B_AI_V1": "v1", "C_AI_FALSIFY": "falsify"}[system]
    reset()
    with SessionLocal() as s:
        inc = _world(s, sc, rng_seed)
        s.commit()
        run = run_ai_investigation(s, inc, protocol=protocol)
        s.commit()
        primary, claimed, confirmed = _finding_claims(s, run)
        f = s.scalars(select(Finding).where(Finding.investigation_id == run.id)).first()
        pin, pout = PRICE_PER_M.get(run.model or "", (0, 0))
        numeric = [t for t in run.trace or [] if t.get("step") == "tool"]
        scored = score(sc, primary, claimed)
        if run.status != "COMPLETED":  # a failed run is a miss, never a correct abstention
            scored |= {k: False for k in ("primary_correct", "appropriate_abstention") if k in scored}
            scored |= {"recall": 0.0} if "recall" in scored else {}
        return {"system": system, "scenario": name, "seed": rng_seed, "status": run.status,
                "error": (run.error or "")[:200] or None, "model": run.model, **scored,
                "server_confirmed": sorted(confirmed),
                "server_confirmed_score": score(sc, primary if primary in confirmed else None, confirmed),
                "verified_claims": f.verified_claim_count if f else 0,
                "unsupported_claims": f.unsupported_claim_count if f else 0,
                "tool_calls": run.tool_calls_used, "tool_sequence": [(t["tool"], t["args"]) for t in numeric],
                "latency_ms": run.latency_ms, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
                "cost_usd": round(run.input_tokens / 1e6 * pin + run.output_tokens / 1e6 * pout, 4),
                "finding": f and {"hypothesis": f.hypothesis, "uncertainty": f.uncertainty,
                                  "confidence": f.confidence, "recommended_action": f.recommended_action}}


def _rate(rows, key):
    vals = [r[key] for r in rows if key in r]
    return {"n": len(vals), "rate": round(sum(vals) / len(vals), 3) if vals else None}


def summarise(rows: list[dict]) -> dict:
    det = [r for r in rows if r["system"] in ("A_BASELINE", "D_CHALLENGER")]
    return {"dev_seeds_1_10": _summarise([r for r in det if r["seed"] in DEV_SEEDS]),
            "heldout_seeds_11_40": _summarise([r for r in det if r["seed"] in HELDOUT_SEEDS]),
            "ai_live_seed_1": _summarise([r for r in rows if r["system"] not in ("A_BASELINE", "D_CHALLENGER")])}


def _summarise(rows: list[dict]) -> dict:
    out = {}
    for system in sorted({r["system"] for r in rows}):
        rs = [r for r in rows if r["system"] == system]  # failed runs included (scored as misses)
        multi = [r for r in rs if len(SUITE[r["scenario"]].truth) > 1]
        out[system] = {
            "runs": len(rs), "failed_runs": sum(1 for r in rows if r["system"] == system
                                                and r.get("status", "COMPLETED") != "COMPLETED"),
            "primary_driver_accuracy": _rate(rs, "primary_correct"),
            "multi_factor_recall": {"n": len(multi), "mean": round(sum(r["recall"] for r in multi) / len(multi), 3)
                                    if multi else None},
            "false_attribution_rate": _rate(rs, "false_attribution"),
            "decoy_hit_rate": _rate([r for r in rs if SUITE[r["scenario"]].decoys], "decoy_hit"),
            "appropriate_abstention_rate": _rate(rs, "appropriate_abstention"),
            "inappropriate_abstention_rate": _rate(rs, "inappropriate_abstention"),
            "mean_tool_calls": round(sum(r["tool_calls"] for r in rs) / len(rs), 1) if rs else None,
            "mean_latency_ms": round(sum(r["latency_ms"] or 0 for r in rs) / len(rs)) if rs else None,
            "mean_cost_usd": round(sum(r["cost_usd"] for r in rs) / len(rs), 4) if rs else None,
        }
        if system.endswith(("V1", "FALSIFY")) and rs:
            v = sum(r["verified_claims"] for r in rs)
            u = sum(r["unsupported_claims"] for r in rs)
            out[system]["evidence_citation_validity"] = f"{v}/{v + u}"
            conf = [r["server_confirmed_score"] for r in rs]
            out[system]["after_server_challenge"] = {
                "false_attribution_rate": _rate(conf, "false_attribution"),
                "primary_driver_accuracy": _rate(conf, "primary_correct")}
    by_scen = {}
    for name in SUITE:
        for system in sorted({r["system"] for r in rows}):
            rs = [r for r in rows if r["system"] == system and r["scenario"] == name
                  and r.get("status", "COMPLETED") == "COMPLETED"]
            if rs:
                by_scen.setdefault(name, {})[system] = {
                    "runs": len(rs), **{k: _rate(rs, k)["rate"] for k in (
                        "primary_correct", "false_attribution", "decoy_hit", "appropriate_abstention")
                                        if any(k in r for r in rs)}}
    return {"by_system": out, "by_scenario": by_scen}


def main(ai_seeds: int, systems: list[str], scenarios: list[str]):
    Base.metadata.create_all(engine)
    names = scenarios or list(SUITE)
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    ai_rows = [r for r in prev.get("runs", []) if r["system"] in ("B_AI_V1", "C_AI_FALSIFY")]
    det_rows = [r for name in names for rs in DET_SEEDS for r in run_deterministic(name, SUITE[name], rs)]
    for rs in range(1, ai_seeds + 1):
        for name in names:
            for system in systems:
                ai_rows = [r for r in ai_rows if (r["system"], r["scenario"], r["seed"]) != (system, name, rs)]
                ai_rows.append(run_ai(name, SUITE[name], rs, system))
                print(system, name, rs, ai_rows[-1]["status"], ai_rows[-1]["claimed"], ai_rows[-1]["cost_usd"],
                      flush=True)
                _write(det_rows, ai_rows)  # never lose a paid run
    _write(det_rows, ai_rows)
    print(json.dumps({k: v["by_system"] for k, v in summarise(det_rows + ai_rows).items()}, indent=1))


def _write(det_rows, ai_rows):
    rows = det_rows + ai_rows
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "as_of": AS_OF.isoformat(),
        "dev_seeds": list(DEV_SEEDS), "heldout_seeds": list(HELDOUT_SEEDS),
        "ai_note": "B (v1) has an 8-call tool budget, C (falsify) 12: budgets differ by protocol design",
        "scenarios": {k: {"description": v.description, "truth": v.truth, "decoys": v.decoys,
                          "expect_abstain": v.expect_abstain, "current_captures": v.current_count,
                          "baseline_per_day": v.baseline_per_day} for k, v in SUITE.items()},
        "data": "frozen synthetic scenarios (origin=SYNTHETIC) in the payops_eval database; no PayPal calls",
        "summary": summarise(rows), "runs": rows}, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai-seeds", type=int, default=0)
    ap.add_argument("--systems", default="B_AI_V1,C_AI_FALSIFY")
    ap.add_argument("--scenarios", default="")
    a = ap.parse_args()
    main(a.ai_seeds, [x for x in a.systems.split(",") if x], [x for x in a.scenarios.split(",") if x])
