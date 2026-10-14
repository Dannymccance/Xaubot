"""200 deterministic, point-in-time OB/FVG research *filters*.

All original 201 Xaubot hypotheses are preserved. Each variation has
meaningful UTC-session, candle-body/momentum, and completed-M5 volatility
rules. No fitting to outcomes, broker orders or provider SL substitution.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .engine import Bar, Candidate, compress

UTC = timezone.utc
BASES = {
    "ob": "ob_continuation__c1__t1",
    "fvg": "fvg_continuation__c1__t2",
}
SESSIONS = ("all_utc", "london_utc", "newyork_utc", "overlap_utc", "asia_utc")
OB_MOMENTUM = ("any", "body20", "body40", "body60", "two_bars", "breakout")
FVG_MOMENTUM = ("any", "body20", "body40", "two_bars")
RANGE_FLOORS = (0., 1.5, 3., 5.)


@dataclass(frozen=True)
class Variant:
    name: str
    base: str
    session: str
    momentum: str
    min_m5_range: float

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def registry() -> tuple[Variant, ...]:
    out = []
    for family, momentum_set in (("ob", OB_MOMENTUM), ("fvg", FVG_MOMENTUM)):
        for i, session in enumerate(SESSIONS):
            for j, momentum in enumerate(momentum_set):
                for k, minimum in enumerate(RANGE_FLOORS):
                    out.append(Variant(
                        name=f"{family}_research__s{i}__m{j}__v{k}",
                        base=BASES[family], session=session, momentum=momentum,
                        min_m5_range=minimum,
                    ))
    # Interleave OB and FVG families, so one-per-day evaluation never
    # waits 120 days before examining the competing FVG family.
    ob = [variant for variant in out if variant.base == BASES["ob"]]
    fvg = [variant for variant in out if variant.base == BASES["fvg"]]
    ordered = []
    for index in range(max(len(ob),len(fvg))):
        if index < len(ob):
            ordered.append(ob[index])
        if index < len(fvg):
            ordered.append(fvg[index])
    assert len(ordered) == 200 and len({v.name for v in ordered}) == 200
    return tuple(ordered)


def _session_ok(stamp: datetime, session: str) -> bool:
    # Fixed UTC windows, not claimed to track London/New York DST or open hours.
    h = stamp.astimezone(UTC).hour
    return {
        "all_utc": True,
        "london_utc": 7 <= h < 16,
        "newyork_utc": 12 <= h < 21,
        "overlap_utc": 12 <= h < 16,
        "asia_utc": 0 <= h < 7,
    }[session]


def matches(variant: Variant, candidate: Candidate,
            current_m5: Bar, previous_m5: Bar | None) -> bool:
    """Apply only completed-M5 inputs available at candidate timestamp."""
    if candidate.strategy != variant.base or candidate.timestamp != current_m5.time:
        return False
    if not _session_ok(candidate.timestamp, variant.session):
        return False
    candle_span = current_m5.high - current_m5.low
    if candle_span + 1e-8 < variant.min_m5_range:
        return False
    side = candidate.side
    body = (current_m5.close - current_m5.open) * side / max(candle_span, .001)
    condition = variant.momentum
    if condition == "any":
        return True
    if condition.startswith("body"):
        return body >= int(condition[4:]) / 100
    if previous_m5 is None:
        return False
    if condition == "two_bars":
        return body > 0 and (previous_m5.close - previous_m5.open) * side > 0
    if condition == "breakout":
        return (current_m5.close > previous_m5.high if side == 1
                else current_m5.close < previous_m5.low)
    raise ValueError(f"Unknown momentum filter: {condition}")


def filtered_candidates(variant: Variant, bases: Iterable[Candidate],
                        current_m5: Bar, previous_m5: Bar | None) -> list[Candidate]:
    out = []
    for candidate in bases:
        if matches(variant,candidate,current_m5,previous_m5):
            out.append(replace(
                candidate,strategy=variant.name,
                rationale=(candidate.rationale
                           + f"; independent OB/FVG research filter: "
                           + f"{variant.session}/{variant.momentum}/"
                           + f"M5range>={variant.min_m5_range:g}"),
            ))
    return out


def filter_fresh_m5(variant: Variant, recent_m1: list[Bar],
                    candidates: Iterable[Candidate]) -> list[Candidate]:
    """Convenience for live-forward journal: no future bars or archive required."""
    m5 = compress(recent_m1[-65:],5,5)
    if not m5:
        return []
    current = m5[-1]
    previous = m5[-2] if len(m5)>1 else None
    return filtered_candidates(variant,candidates,current,previous)
