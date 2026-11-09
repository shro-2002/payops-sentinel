"""Deterministic, explainable refund-rate anomaly detector (P0).

refund_rate(window) = refunds issued in window / captures settled in window.
Fires only when ALL hold (configurable):
  - window captures >= MIN_SAMPLE                (no alerts on tiny samples)
  - window refunds  >= MIN_REFUNDS               (absolute floor)
  - rate >= baseline_rate * MIN_RATIO            (relative jump)
  - rate - baseline_rate >= MIN_ABS_DELTA        (absolute jump; guards near-zero baselines)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Capture, Incident, Refund

DETECTOR = "REFUND_RATE_SPIKE"


@dataclass(frozen=True)
class DetectorConfig:
    window_hours: int = 24
    baseline_days: int = 7
    min_sample: int = 30
    min_refunds: int = 5
    min_ratio: float = 2.0
    min_abs_delta: float = 0.05


@dataclass(frozen=True)
class WindowStats:
    captures: int
    refunds: int
    refunded_minor: int
    rate: float


def window_stats(s: Session, start: datetime, end: datetime) -> WindowStats:
    caps = s.scalar(select(func.count()).select_from(Capture).where(
        Capture.captured_at >= start, Capture.captured_at < end)) or 0
    refunds, refunded = s.execute(select(func.count(), func.coalesce(func.sum(Refund.amount_minor), 0)).where(
        Refund.refunded_at >= start, Refund.refunded_at < end)).one()
    return WindowStats(caps, refunds, int(refunded), round(refunds / caps, 4) if caps else 0.0)


def evaluate(s: Session, as_of: datetime | None = None, cfg: DetectorConfig = DetectorConfig()) -> dict:
    # Windows end on an hour boundary so repeated runs within the hour evaluate the same window (idempotent).
    end = (as_of or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=cfg.window_hours)
    base_start = start - timedelta(days=cfg.baseline_days)
    cur, base = window_stats(s, start, end), window_stats(s, base_start, start)
    checks = {
        "min_sample": cur.captures >= cfg.min_sample,
        "min_refunds": cur.refunds >= cfg.min_refunds,
        "ratio": base.rate == 0 or cur.rate >= base.rate * cfg.min_ratio,
        "abs_delta": cur.rate - base.rate >= cfg.min_abs_delta,
    }
    return {"window_start": start, "window_end": end, "current": asdict(cur), "baseline": asdict(base),
            "config": asdict(cfg), "checks": checks, "fired": all(checks.values()),
            "ratio": round(cur.rate / base.rate, 2) if base.rate else None}


def run_detector(s: Session, as_of: datetime | None = None, cfg: DetectorConfig = DetectorConfig()
                 ) -> Incident | None:
    """Evaluate and, if fired, create (idempotently) one incident for the window."""
    ev = evaluate(s, as_of, cfg)
    s.add(AuditEvent(actor="detector", event_type="DETECTOR_EVALUATED",
                     details={"detector": DETECTOR, "fired": ev["fired"], "checks": ev["checks"],
                              "current": ev["current"], "baseline": ev["baseline"]}))
    if not ev["fired"]:
        return None
    open_inc = s.scalars(select(Incident).where(
        Incident.detector == DETECTOR, Incident.status.in_(("OPEN", "DRIVER_SUPPORTED", "ROOT_CAUSE_IDENTIFIED")),
        Incident.window_end > ev["window_start"]).order_by(Incident.window_end.desc())).first()
    if open_inc is not None:  # an overlapping incident is still open: same problem, no duplicate alert
        return open_inc
    ratio = ev["ratio"] or 99
    severity = "P1" if ratio >= 4 else "P2"
    metrics = {k: v for k, v in ev.items() if k not in ("window_start", "window_end")}
    title = (f"Refund rate {ev['current']['rate']:.1%} vs {ev['baseline']['rate']:.1%} baseline "
             f"({ev['current']['refunds']} refunds / {ev['current']['captures']} captures)")
    created = s.execute(insert(Incident).values(
        detector=DETECTOR, severity=severity, status="OPEN", title=title, window_start=ev["window_start"],
        window_end=ev["window_end"], metrics=metrics,
    ).on_conflict_do_nothing(constraint="uq_incident_window").returning(Incident.id)).scalar()
    inc = s.scalars(select(Incident).where(Incident.detector == DETECTOR,
                                           Incident.window_start == ev["window_start"],
                                           Incident.window_end == ev["window_end"])).one()
    if created is not None:
        s.add(AuditEvent(actor="detector", event_type="INCIDENT_OPENED", incident_id=inc.id,
                         details={"severity": severity, "title": title}))
    return inc
