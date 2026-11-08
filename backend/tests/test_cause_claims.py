"""Cause claims: a matching number never decides causality; the threshold rule on share_of_excess does.
Cases come from the prize-review audit probe (verifier-claim4.py)."""

from types import SimpleNamespace as Call

import pytest
from pydantic import ValidationError

from app.investigator.evidence import CauseClaim, CauseRef, Claim, _root_cause_backed, check_cause_claim, check_claim

RESULT = {"dimension": "fulfillment_partner", "by_value": {
    "SwiftShip-EU": {"current_rate": 0.3111, "baseline_rate": 0.30, "current_refunds": 14, "share_of_excess": 0.6212},
    "NorthPost": {"current_rate": 0.05, "baseline_rate": 0.04, "current_refunds": 2, "share_of_excess": 0.0412}}}
CALLS = {"Q2": Call(status="OK", result=RESULT, tool_name="top_contributors",
                    arguments={"dimension": "fulfillment_partner", "limit": 5})}


def cause(value="SwiftShip-EU", is_cause=True, share="0.6212", qid="Q2", dim="fulfillment_partner"):
    return CauseClaim(dimension=dim, value=value, is_cause=is_cause, explained_share=share, query_id=qid)


def test_audit_counterexample_false_narrative_with_true_number():
    # The number matches, so the claim's VALUE verifies; the narrative is not what is being verified.
    narrative = Claim(statement="SwiftShip-EU refund rate fell to its lowest ever and is NOT a cause", query_id="Q2",
                      metric_path="by_value/SwiftShip-EU/current_rate", value="31.11%")
    assert check_claim(narrative, CALLS)[0] == "VERIFIED"
    # The structured version of "NOT a cause" gets no pass: the slice explains 62% of the excess.
    verdict, src, reason = check_cause_claim(cause(is_cause=False), CALLS)
    assert verdict == "UNRESOLVED" and src == "0.6212" and ">= 0.25" in reason


def test_true_cause_and_true_non_cause_verify():
    assert check_cause_claim(cause(), CALLS)[0] == "CAUSE_VERIFIED"
    assert check_cause_claim(cause(share="62.12%"), CALLS)[0] == "CAUSE_VERIFIED"
    assert check_cause_claim(cause("NorthPost", False, "0.0412"), CALLS)[0] == "NOT_CAUSE_VERIFIED"
    assert check_cause_claim(cause("NorthPost", True, "0.0412"), CALLS)[0] == "CONTRADICTED"


@pytest.mark.parametrize("claim, why", [
    (cause(share="0.90"), "share mismatch"),
    (cause(qid="Q9"), "unknown query"),
    (cause(dim="region"), "ranking is over another dimension"),
    (cause(value="BlueDart-Intl"), "slice not in the ranking"),
    (cause(share="lots"), "non-numeric share"),
])
def test_unreadable_or_mismatched_share_is_unsupported(claim, why):
    assert check_cause_claim(claim, CALLS)[0] == "UNSUPPORTED", why


def test_cause_claim_must_cite_top_contributors():
    calls = {"Q2": Call(status="OK", result=RESULT, tool_name="slice_metric",
                        arguments={"dimension": "fulfillment_partner"})}
    assert check_cause_claim(cause(), calls)[0] == "UNSUPPORTED"


def test_dimension_must_be_from_the_enum():
    with pytest.raises(ValidationError):
        cause(dim="customer_mood")


def test_root_cause_needs_a_passing_cause_claim_on_that_exact_slice():
    rc = CauseRef(dimension="fulfillment_partner", value="SwiftShip-EU")
    assert _root_cause_backed(rc, [(cause(), "CAUSE_VERIFIED")])
    assert not _root_cause_backed(rc, [(cause(is_cause=False), "UNRESOLVED")])
    assert not _root_cause_backed(rc, [(cause("NorthPost", False, "0.0412"), "NOT_CAUSE_VERIFIED")])
    assert not _root_cause_backed(rc, [])  # numeric claims alone (even baseline_rate) never back a root cause
