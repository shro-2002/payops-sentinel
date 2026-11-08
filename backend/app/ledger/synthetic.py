"""Deterministic SYNTHETIC analytical history (clearly labelled origin='SYNTHETIC', ids prefixed 'SYN').

Never presented as real PayPal transactions; real sandbox captures carry origin='SANDBOX_LIVE'.
Each scenario declares its ground truth so the evaluation harness can score detection and root cause.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.ledger.ingest import CaptureDims, upsert_capture, upsert_refund

SKUS = {"HDPH-200": "electronics", "CHRG-30W": "electronics", "MUG-CLASSIC": "home", "TEE-ORG": "apparel",
        "LAMP-LED": "home", "CASE-PRO": "electronics"}
PARTNERS = ("SwiftShip-EU", "ParcelOne", "BlueDart-Intl", "NorthPost")
REGIONS = ("EU", "NA", "APAC", "LATAM")
CHANNELS = ("web", "mobile", "marketplace")
NORMAL_REASONS = ("CHANGED_MIND", "DEFECTIVE", "ITEM_NOT_RECEIVED", "WRONG_ITEM")


@dataclass(frozen=True)
class Driver:
    """In the current window, captures matching `match` are refunded at `rate` with `reason`."""
    match: dict
    rate: float
    reason: str
    weight: float = 0.0  # extra share of current captures forced to match (so the slice is big enough)


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    baseline_per_day: int = 50
    current_count: int = 90
    base_rate: float = 0.04
    current_base_rate: float = 0.04
    drivers: tuple[Driver, ...] = ()
    expect_fire: bool = True
    truth: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (dimension, value) causes
    # Other slices that name the same planted cause: when a driver matches on two dimensions, either one is a
    # correct single-dimension answer. Maps an alternate (dimension, value) to the canonical truth entry.
    equivalents: dict = field(default_factory=dict)

    def canonical(self, cause: tuple[str, str]) -> tuple[str, str]:
        return self.equivalents.get(cause, cause)


SCENARIOS = {s.name: s for s in [
    Scenario("partner_and_sku", "Multi-cause: SwiftShip-EU non-delivery + HDPH-200 defect batch",
             drivers=(Driver({"fulfillment_partner": "SwiftShip-EU", "region": "EU"}, 0.42, "ITEM_NOT_RECEIVED", 0.3),
                      Driver({"product_sku": "HDPH-200"}, 0.35, "DEFECTIVE", 0.2)),
             truth=(("fulfillment_partner", "SwiftShip-EU"), ("product_sku", "HDPH-200")),
             # The first driver is the pair SwiftShip-EU x EU, so region=EU names the same cause.
             equivalents={("region", "EU"): ("fulfillment_partner", "SwiftShip-EU")}),
    Scenario("single_partner", "Single cause: ParcelOne loses parcels",
             drivers=(Driver({"fulfillment_partner": "ParcelOne"}, 0.40, "ITEM_NOT_RECEIVED", 0.35),),
             truth=(("fulfillment_partner", "ParcelOne"),)),
    Scenario("single_sku", "Single cause: CHRG-30W defective batch",
             drivers=(Driver({"product_sku": "CHRG-30W"}, 0.45, "DEFECTIVE", 0.35),),
             truth=(("product_sku", "CHRG-30W"),)),
    Scenario("region_outage", "Single cause: APAC carrier disruption across partners",
             drivers=(Driver({"region": "APAC"}, 0.38, "ITEM_NOT_RECEIVED", 0.35),), truth=(("region", "APAC"),)),
    Scenario("channel_bug", "Single cause: marketplace listing shows wrong item",
             drivers=(Driver({"channel": "marketplace"}, 0.36, "WRONG_ITEM", 0.35),),
             truth=(("channel", "marketplace"),)),
    Scenario("no_anomaly", "Normal day: no incident expected", expect_fire=False),
    Scenario("tiny_sample", "Small sample: 12 captures with 3 refunds must not alert", current_count=12,
             drivers=(Driver({"product_sku": "MUG-CLASSIC"}, 1.0, "DEFECTIVE", 0.25),), expect_fire=False),
    Scenario("high_but_stable", "Refund rate high but equal to baseline (seasonal returns) - no alert",
             base_rate=0.12, current_base_rate=0.12, expect_fire=False),
]}


def _dims(rng: random.Random, force: dict | None = None) -> dict:
    sku = rng.choice(list(SKUS))
    d = {"product_sku": sku, "product_category": SKUS[sku], "region": rng.choice(REGIONS),
         "channel": rng.choice(CHANNELS), "fulfillment_partner": rng.choice(PARTNERS)}
    if force:
        d |= force
        if "product_sku" in force:
            d["product_category"] = SKUS[force["product_sku"]]
    return d


def _matches(d: dict, match: dict) -> bool:
    return all(d.get(k) == v for k, v in match.items())


def seed(s: Session, scenario: Scenario, as_of: datetime, rng_seed: int = 42) -> dict:
    rng = random.Random(f"{scenario.name}:{rng_seed}")
    counter = {"n": 0}

    def make(when: datetime, dims: dict, refund: tuple[str, datetime] | None) -> None:
        counter["n"] += 1
        cid = f"SYN{scenario.name[:3].upper()}{counter['n']:06d}"
        amount = rng.choice(["19.99", "24.50", "39.00", "59.90", "89.00", "129.00"])
        cap = upsert_capture(s, {"id": cid, "status": "COMPLETED", "amount": {"currency_code": "USD", "value": amount},
                                 "create_time": when.isoformat()},
                             dims=CaptureDims(**dims, customer_ref=f"cust-{rng.randint(1000, 9999)}"), origin="SYNTHETIC")
        if refund:
            reason, rwhen = refund
            upsert_refund(s, {"id": f"R{cid}", "status": "COMPLETED", "create_time": rwhen.isoformat(),
                              "amount": {"currency_code": "USD", "value": amount}},
                          capture=cap, reason_code=reason, origin="SYNTHETIC")

    window_start = as_of - timedelta(hours=24)
    # baseline: 7 days before the window, normal refund behaviour, refunds land within the baseline window
    for day in range(7):
        for _ in range(scenario.baseline_per_day):
            when = window_start - timedelta(days=day, minutes=rng.randint(1, 23 * 60))
            refund = None
            if rng.random() < scenario.base_rate:
                rwhen = min(when + timedelta(hours=rng.randint(1, 20)), window_start - timedelta(minutes=1))
                refund = (rng.choice(NORMAL_REASONS), rwhen)
            make(when, _dims(rng), refund)
    # current window
    for _ in range(scenario.current_count):
        when = window_start + timedelta(minutes=rng.randint(1, 14 * 60))
        force = None
        roll = rng.random()
        acc = 0.0
        for drv in scenario.drivers:
            acc += drv.weight
            if roll < acc:
                force = drv.match
                break
        dims = _dims(rng, force)
        rate, reason = scenario.current_base_rate, rng.choice(NORMAL_REASONS)
        for drv in scenario.drivers:
            if _matches(dims, drv.match) and drv.rate > rate:
                rate, reason = drv.rate, drv.reason
        refund = None
        if rng.random() < rate:
            refund = (reason, min(when + timedelta(hours=rng.randint(1, 8)), as_of - timedelta(minutes=1)))
        make(when, dims, refund)
    return {"scenario": scenario.name, "captures": counter["n"], "as_of": as_of.isoformat()}
