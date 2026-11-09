"""Deterministic falsification of suspected-driver hypotheses ("is dimension=value driving this refund spike?").

A slice's share of excess refunds says nothing about causation: a big segment, or a segment correlated with the real
driver, also takes a large share. So a hypothesis is only ASSOCIATION_SUPPORTED when it survives every challenge:

  1. Sample size     the slice has enough captures and refunds to read a rate at all      -> INSUFFICIENT_EVIDENCE
  2. Lift            its refund rate is elevated vs the rest of the window AND vs its own baseline (one-sided
                     exact hypergeometric tests, Bonferroni-corrected over every dimension value present in the
                     window, i.e. every hypothesis that could have been scanned). A large refund count that comes
                     from large volume fails here                                          -> CONTRADICTED
  3. Stratification  the elevation persists inside the strata of every other dimension (Mantel-Haenszel risk
                     difference). If it vanishes within strata of B, B explains it        -> CONTRADICTED
                     If the slice and one B value are the same population                  -> UNRESOLVED
  4. Drill-down      a category whose excess sits in some of its SKUs is refined to them   -> CONTRADICTED
  5. Head-to-head    two survivors that each partly explain the other, with no clear winner -> UNRESOLVED

ASSOCIATION_SUPPORTED means "suspected contributing factor whose association survived these checks", measured on
this ledger. It is never presented as proven causation. Unit of analysis: one capture in the window, refunded in the
window or not. Pure stdlib arithmetic; nothing here trusts model output.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import Capture, Incident, Refund

DIMS = ("fulfillment_partner", "product_sku", "product_category", "region", "channel")
NESTED_IN = {"product_category": "product_sku"}  # every SKU belongs to exactly one category
MIN_SLICE_CAPTURES = 15
MIN_SLICE_REFUNDS = 5
MIN_RATE_LIFT = 0.05        # absolute refund-rate difference worth an operator's time
FAMILY_ALPHA = 0.05         # Bonferroni: per-test alpha = FAMILY_ALPHA / number of dimension values in the window
Z_PERSIST = 1.64            # one-sided 5%: the within-strata lift must still be distinguishable from zero
PERSIST_FRACTION = 0.5      # ... and keep at least half the crude lift
MIN_STRATA_COVERAGE = 0.5   # share of slice captures in strata that also hold comparison captures
CLEAR_WINNER_MARGIN = 0.25  # head-to-head: retained-lift gap needed to prefer one explanation over the other
MAX_CANDIDATES_PER_DIM = 3

COUNTED_REFUND_STATUSES = ("COMPLETED", "PENDING")  # same rule as the ledger's refunded total

SUPPORTED, CONTRADICTED = "ASSOCIATION_SUPPORTED", "CONTRADICTED"
UNRESOLVED, INSUFFICIENT = "UNRESOLVED", "INSUFFICIENT_EVIDENCE"
Hyp = tuple[str, str]


def load_rows(s: Session, start: datetime, end: datetime) -> list[dict]:
    """One row per capture in [start, end): its dimensions and whether it was refunded inside the window."""
    refunded = exists().where(Refund.capture_id == Capture.id, Refund.refunded_at >= start, Refund.refunded_at < end,
                              Refund.status.in_(COUNTED_REFUND_STATUSES))
    q = select(*[getattr(Capture, d) for d in DIMS], refunded).where(Capture.captured_at >= start,
                                                                      Capture.captured_at < end)
    return [dict(zip(DIMS, r[:-1])) | {"refunded": bool(r[-1])} for r in s.execute(q)]


def windows(inc: Incident) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]]:
    days = (inc.metrics or {}).get("config", {}).get("baseline_days", 7)
    return (inc.window_start, inc.window_end), (inc.window_start - timedelta(days=days), inc.window_start)


def _rate(n: int, r: int) -> float | None:
    return round(r / n, 4) if n else None


def _z(n1: int, r1: int, n0: int, r0: int) -> float:
    if not n1 or not n0:
        return 0.0
    p = (r1 + r0) / (n1 + n0)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    return round((r1 / n1 - r0 / n0) / se, 2) if se else 0.0


def _p_upper(n1: int, r1: int, n0: int, r0: int) -> float:
    """One-sided exact p-value that the slice has at least r1 refunds by chance (hypergeometric / Fisher)."""
    if not n1 or not n0:
        return 1.0
    total, refunds = n1 + n0, r1 + r0
    denom = math.comb(total, n1)
    tail = sum(math.comb(refunds, x) * math.comb(total - refunds, n1 - x) for x in range(r1, min(refunds, n1) + 1))
    return tail / denom


def _alpha(rows: list[dict]) -> float:
    """Bonferroni over every value present in the window: all hypotheses that could have been scanned."""
    m = sum(len({r[d] for r in rows}) for d in DIMS)
    return FAMILY_ALPHA / max(m, 1)


def _counts(rows: list[dict], pred) -> tuple[int, int]:
    sel = [r for r in rows if pred(r)]
    return len(sel), sum(r["refunded"] for r in sel)


def _in(r: dict, hyps: list[Hyp]) -> bool:
    return any(r[d] == v for d, v in hyps)


def _crude(cur: list[dict], base: list[dict], dim: str, value: str, exclude: list[Hyp] = ()) -> dict:
    """Slice vs the rest of the window (rows of already-confirmed drivers in other dimensions left out of the rest,
    so a second driver doesn't inflate the comparison), and vs the slice's own baseline."""
    n1, r1 = _counts(cur, lambda r: r[dim] == value)
    n0, r0 = _counts(cur, lambda r: r[dim] != value and not _in(r, exclude))
    nb, rb = _counts(base, lambda r: r[dim] == value)
    return {"captures": n1, "refunds": r1, "rate": _rate(n1, r1),
            "comparison": {"captures": n0, "refunds": r0, "rate": _rate(n0, r0),
                           "excludes": [{"dimension": d, "value": v} for d, v in exclude]},
            "own_baseline": {"captures": nb, "refunds": rb, "rate": _rate(nb, rb)},
            "lift_vs_rest": round(r1 / n1 - r0 / n0, 4) if n1 and n0 else None,
            "z_vs_rest": _z(n1, r1, n0, r0), "z_vs_own_baseline": _z(n1, r1, nb, rb),
            "p_vs_rest": float(f"{_p_upper(n1, r1, n0, r0):.3g}"),
            "p_vs_own_baseline": float(f"{_p_upper(n1, r1, nb, rb):.3g}"), "alpha": float(f"{_alpha(cur):.3g}"),
            "excess_refunds_vs_rest": round(r1 - n1 * (r0 / n0), 2) if n0 else None}


def _elevated(c: dict) -> bool:
    return (c["captures"] >= MIN_SLICE_CAPTURES and c["refunds"] >= MIN_SLICE_REFUNDS
            and (c["lift_vs_rest"] or 0) >= MIN_RATE_LIFT and c["p_vs_rest"] <= c["alpha"]
            and c["p_vs_own_baseline"] <= c["alpha"])


def _stratified(rows: list[dict], dim: str, value: str, by: str) -> dict:
    """Mantel-Haenszel risk difference of slice vs rest, within strata of `by`."""
    num = den = var = 0.0
    covered = 0
    n_slice = sum(r[dim] == value for r in rows)
    for b in {r[by] for r in rows}:
        st = [r for r in rows if r[by] == b]
        n1, r1 = _counts(st, lambda r: r[dim] == value)
        n0, r0 = _counts(st, lambda r: r[dim] != value)
        if not n1 or not n0:
            continue
        covered += n1
        w = n1 * n0 / (n1 + n0)
        p1, p0 = r1 / n1, r0 / n0
        num += w * (p1 - p0)
        den += w
        # floor the binomial variance so a 0% or 100% stratum is not treated as certain
        var += w * w * (max(p1 * (1 - p1), 0.05) / n1 + max(p0 * (1 - p0), 0.05) / n0)
    coverage = round(covered / n_slice, 3) if n_slice else 0.0
    if not den:
        return {"by": by, "coverage": coverage, "adjusted_lift": None, "z": None}
    rd = num / den
    return {"by": by, "coverage": coverage, "adjusted_lift": round(rd, 4),
            "z": round(rd / math.sqrt(var) * den, 2) if var else None}


def _overlap(rows: list[dict], dim: str, value: str, by: str) -> dict[str, float]:
    sl = [r[by] for r in rows if r[dim] == value]
    return {b: sl.count(b) / len(sl) for b in set(sl)} if sl else {}


def _explainer(cur, base, dim, value, by) -> dict | None:
    """The `by` value that best accounts for the slice's elevation: itself elevated, most overlap with the slice."""
    ov = _overlap(cur, dim, value, by)
    hot = [b for b in ov if _elevated(_crude(cur, base, by, b))]
    if not hot:
        return None
    b = max(hot, key=ov.get)
    return {"dimension": by, "value": b, "overlap": round(ov[b], 3)}


def _drill_down(cur, base, dim, value, finer) -> list[dict] | None:
    inner = sorted({r[finer] for r in cur if r[dim] == value})
    hot = [v for v in inner if _elevated(_crude(cur, base, finer, v))]
    if not hot or len(hot) == len(inner):
        return None
    rest = [r for r in cur if not (r[dim] == value and r[finer] in hot)]
    n1, r1 = _counts(rest, lambda r: r[dim] == value)
    n0, r0 = _counts(rest, lambda r: r[dim] != value)
    if r1 >= MIN_SLICE_REFUNDS and n0 and r1 / n1 - r0 / n0 >= MIN_RATE_LIFT and _z(n1, r1, n0, r0) >= Z_PERSIST:
        return None  # the category is elevated even without its hot SKUs
    return [{"dimension": finer, "value": v} for v in hot]


def challenge(cur: list[dict], base: list[dict], dim: str, value: str) -> dict:
    """Run every challenge on one hypothesis. Returns a JSON-serialisable verdict carrying every number it used."""
    c = _crude(cur, base, dim, value)
    out = {"hypothesis": {"dimension": dim, "value": value}, "slice": c, "challenges": [], "status": None,
           "explained_by": None, "indistinguishable_from": None, "refined_to": None}
    if c["captures"] < MIN_SLICE_CAPTURES or c["refunds"] < MIN_SLICE_REFUNDS:
        return out | {"status": INSUFFICIENT, "reason": f"{c['captures']} captures / {c['refunds']} refunds is below "
                      f"the {MIN_SLICE_CAPTURES} / {MIN_SLICE_REFUNDS} minimum: a rate this small is unreliable"}
    if not _elevated(c):
        volume = c["p_vs_own_baseline"] <= c["alpha"]
        return out | {"status": CONTRADICTED, "reason": (
            f"refund rate {c['rate']} vs {c['comparison']['rate']} for the rest of the window (z={c['z_vs_rest']}, "
            f"p={c['p_vs_rest']}, needs p<={c['alpha']}) and {c['own_baseline']['rate']} at baseline "
            f"(p={c['p_vs_own_baseline']})"
            + (": its refunds rose with the spike, but its lift over the rest of the window is not significant "
               "after correcting for every value scanned" if volume else ": not elevated"))}
    crude_lift = c["lift_vs_rest"]
    for by in DIMS:
        if by == dim or NESTED_IN.get(dim) == by or NESTED_IN.get(by) == dim:
            continue
        st = _stratified(cur, dim, value, by)
        st["retained"] = round(st["adjusted_lift"] / crude_lift, 3) if st["adjusted_lift"] is not None else None
        out["challenges"].append(st)
        if st["coverage"] < MIN_STRATA_COVERAGE:
            ov = _overlap(cur, dim, value, by)
            alias = max(ov, key=ov.get)
            if _elevated(_crude(cur, base, by, alias)):
                return out | {"status": UNRESOLVED, "indistinguishable_from": {"dimension": by, "value": alias},
                              "reason": f"{ov[alias]:.0%} of this slice is also {by}={alias}: the data cannot "
                                        f"separate the two explanations"}
            out["untestable_within"] = out.get("untestable_within", []) + [by]
            continue
        if not (st["adjusted_lift"] is not None and st["adjusted_lift"] >= PERSIST_FRACTION * crude_lift
                and (st["z"] or 0) >= Z_PERSIST):
            culprit = _explainer(cur, base, dim, value, by)
            return out | {"status": CONTRADICTED, "explained_by": culprit, "reason": (
                f"rate lift {crude_lift} falls to {st['adjusted_lift']} (z={st['z']}) when compared within each {by}"
                + (f": explained by {by}={culprit['value']}" if culprit else ""))}
    if dim in NESTED_IN and (refined := _drill_down(cur, base, dim, value, NESTED_IN[dim])):
        return out | {"status": CONTRADICTED, "refined_to": refined, "reason": (
            f"the excess sits in {NESTED_IN[dim]}={', '.join(v['value'] for v in refined)}; the rest of "
            f"{dim}={value} is not elevated")}
    skipped = out.get("untestable_within")
    return out | {"status": SUPPORTED, "reason": "elevated vs the rest of the window and its own baseline, and the "
                  "lift persists within every other dimension"
                  + (f" that can be tested (too little overlap to stratify by {', '.join(skipped)})" if skipped else "")
                  + " (an association, not proven causation)"}


def challenge_hypothesis(s: Session, inc: Incident, dim: str, value: str, exclude: Hyp | None = None) -> dict:
    """One hypothesis. `exclude` = an already-supported driver in another dimension: the test then runs on captures
    outside that driver's slice, so its refunds don't inflate the comparison group (disclosed in the result)."""
    cur_w, base_w = windows(inc)
    cur, base = load_rows(s, *cur_w), load_rows(s, *base_w)
    if exclude is None or exclude[0] == dim:
        return challenge(cur, base, dim, value)
    keep = lambda r: r[exclude[0]] != exclude[1]  # noqa: E731
    out = challenge([r for r in cur if keep(r)], [r for r in base if keep(r)], dim, value)
    return out | {"conditional_on_excluding": [{"dimension": exclude[0], "value": exclude[1]}],
                  "reason": out["reason"] + f" (tested on captures outside {exclude[0]}={exclude[1]})"}


def _retained(t: dict, by: str) -> float:
    st = next((c for c in t["challenges"] if c["by"] == by), None)
    return st["retained"] if st and st["retained"] is not None else 1.0


def _head_to_head(tested: dict[Hyp, dict]) -> None:
    """A loser explained by a survivor stays CONTRADICTED only if the survivor clearly holds up better against the
    loser's dimension than the loser held up against the survivor's. Otherwise both are UNRESOLVED."""
    for key, t in list(tested.items()):
        ex = t.get("explained_by")
        if t["status"] != CONTRADICTED or not ex:
            continue
        rival = tested.get((ex["dimension"], ex["value"]))
        if not rival or rival["status"] != SUPPORTED:
            continue
        gap = _retained(rival, key[0]) - _retained(t, ex["dimension"])
        if gap < CLEAR_WINNER_MARGIN:
            reason = (f"{key[0]}={key[1]} and {ex['dimension']}={ex['value']} each absorb much of the other's lift "
                      f"(retained-lift gap {gap:.2f} < {CLEAR_WINNER_MARGIN}): no clear winner at this sample size")
            for k, other in ((key, ex), ((ex["dimension"], ex["value"]), t["hypothesis"])):
                tested[k] = tested[k] | {"status": UNRESOLVED, "reason": reason, "indistinguishable_from": other}


MUTUAL_TOP_K = 3


def _conditional(cur, base, h: Hyp, other: Hyp) -> dict:
    keep = lambda r: r[other[0]] != other[1]  # noqa: E731
    out = challenge([r for r in cur if keep(r)], [r for r in base if keep(r)], *h)
    return out | {"conditional_on_excluding": [{"dimension": other[0], "value": other[1]}],
                  "reason": out["reason"] + f" (tested on captures outside {other[0]}={other[1]})"}


def _mutual_pass(cur, base, tested: dict[Hyp, dict]) -> None:
    """Two independent drivers can hide each other: each inflates the other's comparison group, so neither passes
    alone. Try the strongest lift failures pairwise (different dimensions); support both only if EACH passes the
    strict test on captures outside the other. Disclosed as conditional in both results."""
    lift_fails = [h for h, t in tested.items() if t["status"] == CONTRADICTED
                  and not (t["explained_by"] or t["refined_to"] or t["challenges"])
                  and t["slice"]["refunds"] >= MIN_SLICE_REFUNDS]
    top = sorted(lift_fails, key=lambda h: tested[h]["slice"]["p_vs_rest"])[:MUTUAL_TOP_K]
    for i, a in enumerate(top):
        for b in top[i + 1:]:
            if a[0] == b[0] or tested[a]["status"] == SUPPORTED or tested[b]["status"] == SUPPORTED:
                continue
            ra, rb = _conditional(cur, base, a, b), _conditional(cur, base, b, a)
            if ra["status"] == SUPPORTED and rb["status"] == SUPPORTED:
                tested[a], tested[b] = ra, rb


OVERLAP_NOTE = 0.4
OVERLAP_LIFT = 1.45


def _annotate_overlap(cur: list[dict], tested: dict[Hyp, dict]) -> None:
    """Explain a rejected slice in business terms: how much of it is a supported driver (wording only)."""
    drivers = [h for h, t in tested.items() if t["status"] == SUPPORTED]
    for (dim, value), t in tested.items():
        if t["status"] != CONTRADICTED or t.get("explained_by"):
            continue
        for d in (d for d in drivers if d[0] != dim):
            share = _overlap(cur, dim, value, d[0]).get(d[1], 0)
            overall = sum(r[d[0]] == d[1] for r in cur) / len(cur)
            # only when the driver is clearly over-represented in this slice, not merely common everywhere
            if share >= OVERLAP_NOTE and share >= OVERLAP_LIFT * overall:
                tested[(dim, value)] = t | {"overlaps_supported": {"dimension": d[0], "value": d[1],
                                                                    "share": round(share, 3),
                                                                    "overall_share": round(overall, 3)},
                                            "reason": t["reason"] + f". {share:.0%} of it is {d[0]}={d[1]} (vs "
                                            f"{overall:.0%} of all captures), a supported driver: the overlap, not "
                                            "this slice, carries the excess refunds"}
                break


def compete(s: Session, inc: Incident) -> dict:
    """Generate competing hypotheses across every dimension, try to falsify each, and report what survives.

    Candidates per dimension: the values with the most excess refunds (rate-driven) and the most refunds (volume
    decoys), so the obvious-but-wrong explanations are tested and shown alongside the real ones.
    """
    cur_w, base_w = windows(inc)
    cur, base = load_rows(s, *cur_w), load_rows(s, *base_w)
    cands: list[Hyp] = []
    for dim in DIMS:
        stats = {v: _crude(cur, base, dim, v) for v in {r[dim] for r in cur}}
        by_excess = sorted(stats, key=lambda v: -(stats[v]["excess_refunds_vs_rest"] or 0))
        by_count = sorted(stats, key=lambda v: -stats[v]["refunds"])
        cands += [(dim, v) for v in dict.fromkeys(by_excess[:2] + by_count[:1])][:MAX_CANDIDATES_PER_DIM]
    tested = {h: challenge(cur, base, *h) for h in cands}
    # Second pass: a confirmed driver inflates everyone else's comparison group. Re-test lift failures among the
    # captures that confirmed drivers (in other dimensions) do not touch: a conditional test, disclosed in the result.
    confirmed = [h for h, t in tested.items() if t["status"] == SUPPORTED]
    for h, t in tested.items():
        others = [c for c in confirmed if c[0] != h[0]]
        if others and t["status"] == CONTRADICTED and not (t["explained_by"] or t["refined_to"] or t["challenges"]):
            keep = lambda r: not _in(r, others)  # noqa: E731
            retest = challenge([r for r in cur if keep(r)], [r for r in base if keep(r)], *h)
            if retest["status"] == SUPPORTED:
                tested[h] = retest | {"conditional_on_excluding": [{"dimension": d, "value": v} for d, v in others],
                                      "reason": retest["reason"] + " (tested on captures outside "
                                      + ", ".join(f"{d}={v}" for d, v in others) + ")"}
    if not confirmed:
        _mutual_pass(cur, base, tested)
    _head_to_head(tested)
    _annotate_overlap(cur, tested)
    supported = sorted((t for t in tested.values() if t["status"] == SUPPORTED),
                       key=lambda t: -(t["slice"]["excess_refunds_vs_rest"] or 0))
    unresolved = [t for t in tested.values() if t["status"] == UNRESOLVED]
    if supported:
        decision = "SUSPECTED_DRIVERS_FOUND"
    else:
        decision = "ABSTAIN_INDISTINGUISHABLE" if unresolved else "ABSTAIN_NO_SUPPORTED_DRIVER"
    order = {SUPPORTED: 0, UNRESOLVED: 1, CONTRADICTED: 2, INSUFFICIENT: 3}
    return {"decision": decision, "primary": supported[0]["hypothesis"] if supported else None,
            "supported": [t["hypothesis"] for t in supported],
            "unresolved": [{"hypothesis": t["hypothesis"], "indistinguishable_from": t["indistinguishable_from"]}
                           for t in unresolved],
            "tests": sorted(tested.values(), key=lambda t: (order[t["status"]], t["hypothesis"]["dimension"])),
            "method": {"min_captures": MIN_SLICE_CAPTURES, "min_refunds": MIN_SLICE_REFUNDS, "family_alpha": FAMILY_ALPHA,
                       "lift_test": "one-sided exact hypergeometric, Bonferroni over dimension values in window",
                       "z_persist": Z_PERSIST, "persist_fraction": PERSIST_FRACTION, "min_rate_lift": MIN_RATE_LIFT,
                       "clear_winner_margin": CLEAR_WINNER_MARGIN}}
