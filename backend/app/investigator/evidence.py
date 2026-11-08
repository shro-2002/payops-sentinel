"""Tool execution with per-investigation query ids, and claim verification against those exact results.

A claim is VERIFIED only when:
  1. its query_id belongs to THIS investigation and that call succeeded, and
  2. metric_path resolves inside that call's stored result, and
  3. the claimed number equals the source number (rates may be stated as fraction or percent).
Anything else is UNSUPPORTED and excluded from the verified conclusion.
"""

from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentToolCall, EvidenceRecord, Finding, Incident, InvestigationRun
from app.investigator.tools import TOOLS, ToolArgumentError

RATE_TOLERANCE = Decimal("0.0006")
NUM_TOLERANCE = Decimal("0.006")


class Claim(BaseModel):
    statement: str = Field(max_length=400)
    query_id: str = Field(max_length=16)
    metric_path: str = Field(max_length=200, description="slash path into the tool result, e.g. by_value/X/refund_rate")
    value: str = Field(max_length=32)

    @field_validator("value", mode="before")
    @classmethod
    def _numbers_as_text(cls, v):
        return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


class CauseRef(BaseModel):
    dimension: str
    value: str


class HypothesisNote(BaseModel):
    hypothesis: str
    status: Literal["supported", "rejected", "open"]
    why: str = ""


class FindingDraft(BaseModel):
    hypotheses_considered: list[HypothesisNote] = Field(default_factory=list)
    hypothesis: str
    observed_anomaly: str
    explanation: str
    uncertainty: str
    confidence: Literal["low", "medium", "high"]
    root_cause: CauseRef | None = None
    secondary_causes: list[CauseRef] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list, max_length=20)
    recommended_action: Literal["NO_ACTION", "MANUAL_REVIEW", "PARTIAL_REFUND"]


def execute_tool(s: Session, run: InvestigationRun, inc: Incident, name: str, args: dict) -> AgentToolCall:
    """Run one tool, persist it with a fresh query id. Enforces the per-run tool budget."""
    seq = run.tool_calls_used + 1
    call = AgentToolCall(investigation_id=run.id, query_id=f"Q{seq}", seq=seq, tool_name=str(name)[:48],
                         arguments=args if isinstance(args, dict) else {"_raw": str(args)[:200]}, status="OK")
    run.tool_calls_used = seq
    t0 = time.perf_counter()
    if seq > run.max_tool_calls:
        call.status, call.error = "REJECTED", "tool budget exhausted"
    elif name not in TOOLS:
        call.status, call.error = "REJECTED", f"unknown tool {name!r}; allowed: {sorted(TOOLS)}"
    elif not isinstance(args, dict):
        call.status, call.error = "REJECTED", "arguments must be an object"
    else:
        try:
            call.result = TOOLS[name](s, inc, args)
        except ToolArgumentError as e:
            call.status, call.error = "REJECTED", str(e)
    call.duration_ms = int((time.perf_counter() - t0) * 1000)
    s.add(call)
    s.flush()
    return call


def _resolve(result: dict, path: str):
    node = result
    for part in path.split("/"):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise KeyError(part)
    return node


def _num(text: str) -> tuple[Decimal, bool]:
    t = text.strip().replace(",", "").replace("$", "")
    is_pct = t.endswith("%")
    d = Decimal(t.rstrip("%"))
    if not d.is_finite():
        raise InvalidOperation("non-finite")
    return d, is_pct


RATE_LEAVES = ("rate", "share_of_excess")


def check_claim(claim: Claim, calls_by_qid: dict[str, AgentToolCall]) -> tuple[str, str | None, str | None]:
    call = calls_by_qid.get(claim.query_id)
    if call is None:
        return "UNSUPPORTED", None, f"query_id {claim.query_id} does not belong to this investigation"
    if call.status != "OK" or call.result is None:
        return "UNSUPPORTED", None, f"{claim.query_id} did not succeed"
    try:
        source = _resolve(call.result, claim.metric_path)
    except KeyError as e:
        return "UNSUPPORTED", None, f"metric_path segment {e} not in {claim.query_id} result"
    if isinstance(source, (dict, list)) or source is None:
        return "UNSUPPORTED", str(source)[:64], "metric_path does not point at a scalar"
    parts = claim.metric_path.split("/")
    # The statement must name the slice it cites (e.g. a claim on by_value/NorthPost/... must mention NorthPost).
    if len(parts) >= 2 and parts[0] in ("by_value", "by_reason") and parts[1].lower() not in claim.statement.lower():
        return "UNSUPPORTED", str(source)[:64], f"statement does not name the cited slice '{parts[1]}'"
    try:
        claimed, is_pct = _num(claim.value)
        src = Decimal(str(source))
    except InvalidOperation:
        if isinstance(source, bool):  # booleans: "true"/"True" are the same fact
            ok = claim.value.strip().lower() == str(source).lower()
        else:
            ok = str(source).strip() == claim.value.strip()
        return ("VERIFIED" if ok else "UNSUPPORTED"), str(source)[:64], None if ok else "value mismatch"
    if is_pct:
        if not parts[-1].endswith(RATE_LEAVES):
            return "UNSUPPORTED", str(source), "percent stated for a non-rate field"
        claimed = claimed / 100
    tol = RATE_TOLERANCE if (is_pct or abs(src) < 1) else NUM_TOLERANCE
    if abs(claimed - src) <= tol:
        return "VERIFIED", str(source), None
    return "UNSUPPORTED", str(source), f"claimed {claim.value} but source has {source}"


def persist_finding(s: Session, run: InvestigationRun, inc: Incident, draft: FindingDraft) -> Finding:
    calls = s.scalars(select(AgentToolCall).where(AgentToolCall.investigation_id == run.id)).all()
    by_qid = {c.query_id: c for c in calls}
    rc = draft.root_cause
    f = Finding(incident_id=inc.id, investigation_id=run.id, hypothesis=draft.hypothesis,
                observed_anomaly=draft.observed_anomaly, explanation=draft.explanation, uncertainty=draft.uncertainty,
                confidence=draft.confidence, root_cause_dimension=rc.dimension if rc else None,
                root_cause_value=rc.value if rc else None, recommended_action=draft.recommended_action)
    s.add(f)
    s.flush()
    verified = unsupported = 0
    for claim in draft.claims:
        verdict, src, reason = check_claim(claim, by_qid)
        call = by_qid.get(claim.query_id)
        s.add(EvidenceRecord(finding_id=f.id, tool_call_id=call.id if call else None, query_id=claim.query_id,
                             statement=claim.statement, metric_path=claim.metric_path, claimed_value=claim.value,
                             source_value=src, verification=verdict, reason=reason))
        verified += verdict == "VERIFIED"
        unsupported += verdict != "VERIFIED"
    f.verified_claim_count, f.unsupported_claim_count = verified, unsupported
    verified_values = [Decimal(src) for c in draft.claims for v, src, _ in [check_claim(c, by_qid)]
                       if v == "VERIFIED" and src is not None and _is_num(src)]
    prose = " ".join([draft.explanation, draft.hypothesis, draft.observed_anomaly])
    # A root cause only counts as identified when it is backed by at least one verified claim.
    if rc and _root_cause_backed(rc, draft.claims, by_qid):
        inc.root_cause_identified = True
        inc.status = "ROOT_CAUSE_IDENTIFIED" if inc.status == "OPEN" else inc.status
    run.trace = list(run.trace or []) + [{"step": "prose_unverified_numbers",
                                          "value": unbacked_numbers(prose, verified_values)},
                                         {"step": "secondary_causes",
                                          "value": [c.model_dump() for c in draft.secondary_causes]},
                                         {"step": "hypotheses", "value": [h.model_dump() for h in draft.hypotheses_considered]}]
    return f


# Skip digits glued to identifiers (HDPH-200, CHRG-30W, Q7).
NUM_IN_TEXT = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)(%?)(?![\w-])")


def _is_num(text: str) -> bool:
    try:
        Decimal(text)
        return True
    except InvalidOperation:
        return False


def unbacked_numbers(prose: str, verified: list[Decimal]) -> list[str]:
    """Numbers stated in prose that match no verified claim value (fraction/percent aware). Small integers <= 10
    are ignored as they are usually counts of things like 'two causes'."""
    out = []
    for raw, pct in NUM_IN_TEXT.findall(prose):
        n = Decimal(raw)
        if not pct and "." not in raw and n <= 10:
            continue
        candidates = [n / 100] if pct else [n, n / 100]
        if not any(abs(c - v) <= RATE_TOLERANCE or abs(c - v) <= NUM_TOLERANCE and abs(v) >= 1
                   for c in candidates for v in verified):
            out.append(raw + pct)
    return sorted(set(out))


def _root_cause_backed(rc: CauseRef, claims: list[Claim], by_qid: dict[str, AgentToolCall]) -> bool:
    """A root cause counts as identified only if a VERIFIED claim cites that exact dimension value."""
    from app.investigator.tools import DIMENSIONS
    if rc.dimension not in DIMENSIONS:
        return False
    for c in claims:
        call = by_qid.get(c.query_id)
        if call is None or check_claim(c, by_qid)[0] != "VERIFIED":
            continue
        args = call.arguments or {}
        in_path = f"by_value/{rc.value}/" in c.metric_path + "/"
        dim_ok = args.get("dimension") == rc.dimension or args.get("by") == rc.dimension
        scoped = args.get("dimension") == rc.dimension and args.get("value") == rc.value
        if (in_path and dim_ok) or scoped:
            return True
    return False
