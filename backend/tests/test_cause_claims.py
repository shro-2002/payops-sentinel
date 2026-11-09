"""Cause claims are information only: the share check reports whether the cited share is right and above 0.25,
and never decides whether a slice is a driver (that is the falsification engine's job, see test_hypotheses).
Cases come from the prize-review audit probe (verifier-claim4.py)."""

from types import SimpleNamespace as Call

import pytest
from pydantic import ValidationError

from app.investigator.evidence import CauseClaim, Claim, check_cause_claim, check_claim

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
    assert verdict == "SHARE_MATERIAL" and src == "0.6212" and "not a driver test" in reason


def test_share_check_reports_share_only():
    assert check_cause_claim(cause(), CALLS)[0] == "SHARE_MATERIAL"
    assert check_cause_claim(cause(share="62.12%"), CALLS)[0] == "SHARE_MATERIAL"
    assert check_cause_claim(cause("NorthPost", False, "0.0412"), CALLS)[0] == "SHARE_IMMATERIAL"
    assert check_cause_claim(cause("NorthPost", True, "0.0412"), CALLS)[0] == "SHARE_IMMATERIAL"


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
