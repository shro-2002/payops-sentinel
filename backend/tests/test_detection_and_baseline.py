from app.detection.refund_rate import run_detector
from app.investigator.agent import run_baseline_investigation
from app.ledger.synthetic import SCENARIOS, seed
from conftest import AS_OF
import pytest


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_detector_matches_scenario_ground_truth(db, name):
    seed(db, SCENARIOS[name], AS_OF)
    inc = run_detector(db, AS_OF)
    assert (inc is not None) == SCENARIOS[name].expect_fire, inc and inc.metrics


def test_detector_is_idempotent_for_same_window(db):
    seed(db, SCENARIOS["single_partner"], AS_OF)
    a, b = run_detector(db, AS_OF), run_detector(db, AS_OF)
    assert a.id == b.id


def test_baseline_finds_single_cause_and_claims_verify(db):
    seed(db, SCENARIOS["single_partner"], AS_OF)
    inc = run_detector(db, AS_OF)
    run = run_baseline_investigation(db, inc)
    from app.db.models import Finding
    f = db.query(Finding).filter_by(investigation_id=run.id).one()
    assert (f.root_cause_dimension, f.root_cause_value) == ("fulfillment_partner", "ParcelOne")
    assert f.unsupported_claim_count == 0 and f.verified_claim_count == 2
    assert run.tool_calls_used == 4
