"""Point-in-time, experimental SMC strategy engine. No broker order interface."""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
FAMILIES = (
    "ob_reversal", "ob_continuation", "fvg_reversal", "fvg_continuation",
    "rbs_sbr", "supply_demand", "liquidity_sweep", "false_breakout",
    "structure_continuation", "double_top_bottom",
)


@dataclass(frozen=True)
class Bar:
    time: datetime                  # UTC opening timestamp for this M1 bar
    open: float
    high: float
    low: float
    close: float
    open_bid: float | None = None
    high_bid: float | None = None
    low_bid: float | None = None
    close_bid: float | None = None
    open_ask: float | None = None
    high_ask: float | None = None
    low_ask: float | None = None
    close_ask: float | None = None


@dataclass(frozen=True)
class Zone:
    kind: str
    side: int
    low: float
    high: float
    formed: datetime
    timeframe: str


@dataclass(frozen=True)
class Candidate:
    timestamp: datetime
    strategy: str
    family: str
    side: int
    ref_price: float
    zone_low: float
    zone_high: float
    entry_low: float
    entry_high: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    tp3_source: str
    score: int                # HEURISTIC - NOT calibrated probability
    rationale: str
    regime: str

    @property
    def event_id(self) -> str:
        payload = f"{self.strategy}|{self.timestamp.isoformat()}|{self.side}|{self.zone_low}|{self.zone_high}"
        return hashlib.sha256(payload.encode()).hexdigest()[:20]

    def to_dict(self) -> dict:
        return {**asdict(self), "timestamp": self.timestamp.isoformat(),
                "side": "BUY" if self.side == 1 else "SELL", "event_id": self.event_id}


def strategies() -> tuple[str, ...]:
    return ("GWS_PRIMARY",) + tuple(
        f"{family}__c{confirm}__t{timing}"
        for family in FAMILIES for confirm in range(4) for timing in range(5)
    )


def read_m1(path: str | Path) -> list[Bar]:
    """CSV timestamps MUST be timezone-aware UTC bar OPEN times. No silent repair."""
    out: list[Bar] = []
    optional = ("open_bid", "high_bid", "low_bid", "close_bid",
                "open_ask", "high_ask", "low_ask", "close_ask")
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "open", "high", "low", "close"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing required CSV columns: {sorted(required)}")
        has_quotes = any(k in (reader.fieldnames or []) for k in optional)
        if has_quotes and not all(k in reader.fieldnames for k in optional):
            raise ValueError("Provide all eight bid/ask OHLC fields or none")
        for i, row in enumerate(reader, 2):
            try:
                raw_time = row["timestamp"].strip().replace("Z", "+00:00")
                stamp = datetime.fromisoformat(raw_time)
                if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
                    raise ValueError("timestamp must be UTC with +00:00/Z suffix")
                stamp = stamp.astimezone(UTC)
                if stamp.second or stamp.microsecond:
                    raise ValueError("M1 opening timestamp must align to full minute")
                values = [float(row[k]) for k in ("open", "high", "low", "close")]
                import math
                if not all(math.isfinite(v) and v > 0 for v in values):
                    raise ValueError("nonfinite or nonpositive OHLC")
                if values[1] < max(values[0], values[2], values[3]) or values[2] > min(values[0], values[1], values[3]):
                    raise ValueError("invalid OHLC ordering")
                quotes = {k: float(row[k]) for k in optional} if has_quotes else {}
                if has_quotes:
                    for side in ("bid", "ask"):
                        a, h, l, c = (quotes[f"{k}_{side}"] for k in ("open", "high", "low", "close"))
                        if not all(math.isfinite(v) and v > 0 for v in (a, h, l, c)):
                            raise ValueError("invalid bid/ask values")
                        if h < max(a, l, c) or l > min(a, h, c):
                            raise ValueError("invalid bid/ask OHLC")
                    if quotes["open_bid"] > quotes["open_ask"] or quotes["close_bid"] > quotes["close_ask"]:
                        raise ValueError("inverted bid/ask quote")
                if out and stamp <= out[-1].time:
                    raise ValueError("timestamps not strictly increasing")
                out.append(Bar(stamp, *values, **quotes))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"CSV line {i}: {error}") from error
    if not out:
        raise ValueError("Empty M1 feed")
    return out


def compress(bars: list[Bar], minutes: int, min_count: int) -> list[Bar]:
    """Emit ONLY completed UTC-aligned time buckets; no forming HTF candles."""
    if not bars:
        return []
    groups: dict[int, list[Bar]] = {}
    for b in bars:
        bucket = int(b.time.timestamp() // (minutes * 60))
        groups.setdefault(bucket, []).append(b)
    observed_end = bars[-1].time + timedelta(minutes=1)
    out = []
    for bucket, group in groups.items():
        start = datetime.fromtimestamp(bucket * minutes * 60, UTC)
        if start + timedelta(minutes=minutes) > observed_end or len(group) < min_count:
            continue
        if minutes == 5 and (
            len(group) != 5 or any(b.time != start + timedelta(minutes=i) for i, b in enumerate(group))
        ):
            continue
        out.append(Bar(start + timedelta(minutes=minutes), group[0].open,
                       max(b.high for b in group), min(b.low for b in group),
                       group[-1].close))
    return out


def _zone(kind: str, side: int, lo: float, hi: float, bar: Bar, tf: str) -> Zone:
    return Zone(kind, side, round(lo, 3), round(hi, 3), bar.time, tf)


def structural_zones(h1: list[Bar], h4: list[Bar], daily: list[Bar]) -> list[Zone]:
    zones: list[Zone] = []
    for tf, frames in (("H1", h1), ("H4", h4), ("D1", daily)):
        for i in range(max(5, len(frames) - 40), len(frames)):
            c = frames[i]
            a, b = frames[i-2], frames[i-1]
            if a.high < c.low and b.close > b.open:
                zones.append(_zone("fvg", 1, a.high, c.low, c, tf))
            if a.low > c.high and b.close < b.open:
                zones.append(_zone("fvg", -1, c.high, a.low, c, tf))
            prior = frames[i-5:i]
            resistance = max(x.high for x in prior)
            support = min(x.low for x in prior)
            if c.close > resistance:
                zones.append(_zone("flip", 1, resistance - .7, resistance + .7, c, tf))
                if b.close < b.open:
                    zones.append(_zone("ob", 1, b.low, b.open, c, tf))
            if c.close < support:
                zones.append(_zone("flip", -1, support - .7, support + .7, c, tf))
                if b.close > b.open:
                    zones.append(_zone("ob", -1, b.open, b.high, c, tf))
            # Already-confirmed turning points, rather than future-pivot labels.
            if b.low < a.low and b.low < c.low:
                zones.append(_zone("sd", 1, b.low, min(b.open, b.close), c, tf))
            if b.high > a.high and b.high > c.high:
                zones.append(_zone("sd", -1, max(b.open, b.close), b.high, c, tf))
    return zones


def _m5_zones(m5: list[Bar]) -> list[Zone]:
    if len(m5) < 10:
        return []
    last = m5[-1]
    prev = m5[-7:-1]
    hi = max(b.high for b in prev)
    lo = min(b.low for b in prev)
    out = []
    if last.low < lo and last.close > lo:
        out.append(_zone("sweep", 1, last.low, lo, last, "M5"))
        out.append(_zone("fakeout", 1, last.low, lo, last, "M5"))
    if last.high > hi and last.close < hi:
        out.append(_zone("sweep", -1, hi, last.high, last, "M5"))
        out.append(_zone("fakeout", -1, hi, last.high, last, "M5"))
    if last.close > hi:
        out.append(_zone("bos", 1, hi - .75, hi + .75, last, "M5"))
    if last.close < lo:
        out.append(_zone("bos", -1, lo - .75, lo + .75, last, "M5"))
    # Similar recent extremities form preliminary double-top/bottom candidates.
    a, b = m5[-9:-5], m5[-5:-1]
    alo, blo = min(x.low for x in a), min(x.low for x in b)
    ahi, bhi = max(x.high for x in a), max(x.high for x in b)
    if abs(alo - blo) <= 1.5 and last.close > max(alo, blo) + .6:
        out.append(_zone("double", 1, min(alo, blo), max(alo, blo) + .7, last, "M5"))
    if abs(ahi - bhi) <= 1.5 and last.close < min(ahi, bhi) - .6:
        out.append(_zone("double", -1, min(ahi, bhi) - .7, max(ahi, bhi), last, "M5"))
    return out


KIND = {
    "ob_reversal": "ob", "ob_continuation": "ob",
    "fvg_reversal": "fvg", "fvg_continuation": "fvg",
    "rbs_sbr": "flip", "supply_demand": "sd",
    "liquidity_sweep": "sweep", "false_breakout": "fakeout",
    "structure_continuation": "bos", "double_top_bottom": "double",
}


def _confirmation(m5: list[Bar], side: int, profile: int) -> bool:
    c, p = m5[-1], m5[-2]
    span = max(c.high-c.low, .001)
    direction = (c.close-c.open)*side
    if profile == 0:   # directional rejection wick
        wick = min(c.open,c.close)-c.low if side == 1 else c.high-max(c.open,c.close)
        return direction > 0 and wick / span >= .25
    if profile == 1:   # directional engulfing body
        return direction > 0 and abs(c.close-c.open) > abs(p.close-p.open) and c.low <= p.low and c.high >= p.high
    if profile == 2:   # structural close beyond 4 previous bars
        return c.close > max(x.high for x in m5[-5:-1]) if side == 1 else c.close < min(x.low for x in m5[-5:-1])
    # directional follow-through; sweeps are deliberately NOT compulsory
    return direction > 0 and (c.close-p.close)*side > .5


def _timing(m5: list[Bar], side: int, timing: int, z: Zone) -> bool:
    c, p = m5[-1], m5[-2]
    span = max(c.high-c.low, .001)
    if timing == 0:
        return True
    if timing == 1:
        return (c.close-p.close)*side >= .25
    if timing == 2:
        return abs(c.close - (z.low+z.high)/2) <= 2
    if timing == 3:
        return (c.close-c.open)*side / span >= .45
    return ((c.close-c.low)/span >= .7 if side == 1 else (c.high-c.close)/span >= .7)


def _bias(h1: list[Bar], h4: list[Bar]) -> int:
    frame = h4 if len(h4) >= 6 else h1
    if len(frame) < 6:
        return 0
    return (1 if frame[-1].close > frame[-6].close else
            -1 if frame[-1].close < frame[-6].close else 0)


def _candidate(name: str, family: str, side: int, z: Zone, last: Bar,
               frames: list[Bar], score: int, rationale: str) -> Candidate | None:
    ref = round(last.close, 2)  # provisional technical anchor, NOT learned GWS rule
    # Structural invalidation with explicit provisional buffer.
    stop = min(z.low, last.low)-.8 if side == 1 else max(z.high, last.high)+.8
    distance = (ref-stop)*side
    if distance < 4:
        stop = ref - 4*side
        distance = 4
    if distance > 60:
        return None
    stop = round(stop, 2)
    tp1, tp2 = round(ref+4*side,2), round(ref+6.5*side,2)
    # Opposite structural swing extrema from completed higher-timeframe candles.
    objectives = [round(b.high if side == 1 else b.low, 2) for b in frames
                  if ((b.high if side == 1 else b.low)-ref)*side > 8]
    if objectives:
        tp3 = min(objectives) if side == 1 else max(objectives)
        source = "historical_htf_extreme_candidate"
    else:
        tp3 = round(ref + side*max(3*distance, 9),2)
        source = "fallback_3R_hypothesis"
    return Candidate(last.time, name, family, side, ref, round(z.low,2), round(z.high,2),
                     round(ref-3,2) if side == 1 else ref,
                     ref if side == 1 else round(ref+3,2),
                     stop, tp1, tp2, tp3, source, score, rationale,
                     "scalp" if distance <= 14 else "structural")


def evaluate(bars: list[Bar]) -> list[Candidate]:
    """Evaluate at a CLOSED M5 timestamp; all higher-timeframe data is completed."""
    m5 = compress(bars, 5, 5)
    if len(m5) < 12 or m5[-1].time != bars[-1].time + timedelta(minutes=1):
        return []
    h1 = compress(bars, 60, 50)
    h4 = compress(bars, 240, 180)
    d1 = compress(bars, 1440, 1000)
    if len(h1) < 7:
        return []
    zlist = structural_zones(h1, h4, d1) + _m5_zones(m5)
    last = m5[-1]
    bias = _bias(h1,h4)
    zones = [z for z in zlist
             if 0 <= (last.time-z.formed).total_seconds() <= 14*86400
             and z.low <= last.high+1 and z.high >= last.low-1
             and z.low < z.high]
    out: list[Candidate] = []
    # Primary model: multiple independent structural sources, sweep optional.
    for side in (1, -1):
        available = [z for z in zones if z.side == side and z.kind in {"ob","fvg","flip","sd","sweep"}]
        types = {z.kind for z in available}
        if len(types) >= 2 and (_confirmation(m5,side,0) or _confirmation(m5,side,1)
                                or _confirmation(m5,side,2) or _confirmation(m5,side,3)):
            chosen = sorted(available, key=lambda z: (abs(last.close-(z.low+z.high)/2),
                                                       z.timeframe!="H4"))[0]
            score = min(95, 35+10*len(types)+(10 if side==bias else 0))
            item = _candidate("GWS_PRIMARY","gws_replica",side,chosen,last,h1+h4+d1,
                              score, f"Distinct confluence: {','.join(sorted(types))}; bias={bias}; rule provisional")
            if item:
                out.append(item)
    for family in FAMILIES:
        kind = KIND[family]
        for side in (1,-1):
            matching = [z for z in zones if z.kind==kind and z.side==side]
            if not matching:
                continue
            if family.endswith("_continuation") and bias != side:
                continue
            if family.endswith("_reversal") and bias == side:
                continue
            chosen = min(matching, key=lambda z: abs(last.close-(z.low+z.high)/2))
            for c in range(4):
                if not _confirmation(m5,side,c):
                    continue
                for t in range(5):
                    if not _timing(m5,side,t,chosen):
                        continue
                    name = f"{family}__c{c}__t{t}"
                    item = _candidate(name,family,side,chosen,last,h1+h4+d1,
                                      min(95,35+10*(bias==side)+5*c+2*t),
                                      f"{kind} {chosen.timeframe}; confirmation={c}; timing={t}; bias={bias}")
                    if item:
                        out.append(item)
    return out
