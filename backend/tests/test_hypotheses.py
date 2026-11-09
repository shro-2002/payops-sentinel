"""Falsification engine regression suite: a wrong hypothesis must never be supported merely because it holds a big
share of the excess, and the engine must abstain when the data cannot single out a driver.

Each case is checked on several RNG draws of its scenario (seeded, so deterministic), because one lucky draw proves
nothing about a statistical rule."""

from datetime import timedelta

import pytest

from app.db.models import Incident
from app.detection.refund_rate import run_detector
from app.investigator.hypotheses import (CONTRADICTED, INSUFFICIENT, SUPPORTED, UNRESOLVED, challenge,
                                         challenge_hypothesis, compete)
from app.ledger.synthetic import ADVERSARIAL, seed
from conftest import AS_OF

SEEDS = (1, 2, 3, 4, 5)


def _world(db, name, rng_seed):
    seed(db, ADVERSARIAL[name], AS_OF, rng_seed=rng_seed)
    inc = run_detector(db, AS_OF)
    if inc is None:  # no-anomaly world: investigate the same window anyway
        inc = Incident(detector="MANUAL", severity="P3", title="manual", window_start=AS_OF - timedelta(hours=24),
                       window_end=AS_OF, metrics={})
    return inc


def _supported(report):
    return {(h["dimension"], h["value"]) for h in report["supported"]}


@pytest.mark.parametrize("rng_seed", SEEDS)
def test_confounded_channel_is_contradicted_and_partner_supported(db, rng_seed):
    inc = _world(db, "adv_confounded_channel", rng_seed)
    mobile = challenge_hypothesis(db, inc, "channel", "mobile")
    assert mobile["status"] != SUPPORTED, mobile["reason"]
    report = compete(db, inc)
    assert ("channel", "mobile") not in _supported(report)
    assert report["primary"] == {"dimension": "fulfillment_partner", "value": "NorthPost"}


@pytest.mark.parametrize("rng_seed", SEEDS)
def test_region_explained_by_product_batch(db, rng_seed):
    inc = _world(db, "adv_region_vs_batch", rng_seed)
    report = compete(db, inc)
    assert ("region", "LATAM") not in _supported(report)
    assert report["primary"] == {"dimension": "product_sku", "value": "LAMP-LED"}
    home = challenge_hypothesis(db, inc, "product_category", "home")
    assert home["status"] != SUPPORTED, home["reason"]  # refined to the SKU


@pytest.mark.parametrize("rng_seed", SEEDS)
def test_high_volume_segment_is_not_a_driver(db, rng_seed):
    inc = _world(db, "adv_volume_segment", rng_seed)
    web = challenge_hypothesis(db, inc, "channel", "web")
    assert web["status"] == CONTRADICTED and web["slice"]["refunds"] > 0, web["reason"]
    assert compete(db, inc)["primary"] == {"dimension": "product_sku", "value": "CASE-PRO"}


@pytest.mark.parametrize("rng_seed", SEEDS)
def test_two_independent_factors_are_both_supported(db, rng_seed):
    inc = _world(db, "adv_two_factors", rng_seed)
    assert {("fulfillment_partner", "BlueDart-Intl"), ("product_sku", "MUG-CLASSIC")} <= _supported(compete(db, inc))


@pytest.mark.parametrize("rng_seed", SEEDS)
def test_indistinguishable_explanations_abstain(db, rng_seed):
    inc = _world(db, "adv_indistinguishable", rng_seed)
    for dim, value in (("fulfillment_partner", "ParcelOne"), ("product_sku", "TEE-ORG")):
        t = challenge_hypothesis(db, inc, dim, value)
        assert t["status"] in (UNRESOLVED, CONTRADICTED), t["reason"]
    report = compete(db, inc)
    assert not _supported(report) & {("fulfillment_partner", "ParcelOne"), ("product_sku", "TEE-ORG")}
    assert report["decision"] == "ABSTAIN_INDISTINGUISHABLE"


@pytest.mark.parametrize("rng_seed", SEEDS)
def test_low_sample_slice_is_insufficient_evidence(db, rng_seed):
    inc = _world(db, "adv_low_sample", rng_seed)
    kiosk = challenge_hypothesis(db, inc, "channel", "kiosk")
    assert kiosk["status"] == INSUFFICIENT and kiosk["slice"]["rate"] >= 0.3, kiosk
    assert compete(db, inc)["primary"] == {"dimension": "fulfillment_partner", "value": "SwiftShip-EU"}


@pytest.mark.parametrize("rng_seed", (1, 2, 3, 4))
def test_no_anomaly_names_no_driver(db, rng_seed):
    report = compete(db, _world(db, "adv_no_anomaly", rng_seed))
    assert report["decision"] == "ABSTAIN_NO_SUPPORTED_DRIVER" and not report["supported"]


def test_big_share_of_excess_alone_never_supports():
    """The audit counterexample: an innocent slice that takes most of the excess (because it co-occurs with the real
    driver) must be contradicted, with the real driver named as the explanation."""
    rows = []
    for partner, channel, n, refunded in [("Bad", "mobile", 60, 24), ("Bad", "web", 10, 4),
                                          ("Good", "mobile", 20, 1), ("Good", "web", 90, 4)]:
        rows += [{"fulfillment_partner": partner, "channel": channel, "product_sku": "S", "product_category": "C",
                  "region": "EU", "refunded": i < refunded} for i in range(n)]
    base = [r | {"refunded": i % 25 == 0} for i, r in enumerate(rows)]
    mobile = challenge(rows, base, "channel", "mobile")
    assert mobile["slice"]["excess_refunds_vs_rest"] > 10  # it does look guilty on a share basis
    assert mobile["status"] == CONTRADICTED
    assert mobile["explained_by"]["dimension"] == "fulfillment_partner"
    assert mobile["explained_by"]["value"] == "Bad"
    assert challenge(rows, base, "fulfillment_partner", "Bad")["status"] == SUPPORTED
