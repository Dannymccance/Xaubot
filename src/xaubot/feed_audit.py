"""Audit UTC M1 research feed provenance, gaps and stale-source limitations.

This module NEVER infers that markets are open/closed from missing candles.
Broker UTC offset is only provisionally configured in the Wine bridge; its
real-world accuracy must be independently verified for each broker/date range.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .engine import Bar, read_m1

UTC = timezone.utc


def feed_sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def audit_feed(path: Path, bars: list[Bar] | None = None,
               now: datetime | None = None) -> dict:
    """Produce reproducible research-feed metadata, never an accuracy claim."""
    path = Path(path)
    if bars is None:
        bars = read_m1(path)
    if not bars:
        raise ValueError("No bars to audit")
    clock = (now or datetime.now(UTC)).astimezone(UTC)
    first, last = bars[0].time, bars[-1].time
    last_close = last + timedelta(minutes=1)
    if last_close > clock + timedelta(seconds=15):
        raise ValueError("M1 feed extends beyond UTC clock; verify broker offset")
    if any(b.time.tzinfo is None or b.time.utcoffset() != timedelta(0)
           for b in bars):
        raise ValueError("Bars must be timezone-aware UTC")
    gap_count = 0
    longest_gap = 0
    missing_minutes = 0
    for prev, curr in zip(bars, bars[1:]):
        delta = int((curr.time - prev.time).total_seconds())
        if delta < 60 or delta % 60:
            raise ValueError("Invalid M1 chronology or alignment in research feed")
        if delta > 60:
            gap_count += 1
            missing = delta // 60 - 1
            missing_minutes += missing
            longest_gap = max(longest_gap, missing)
    manifest_file = path.with_suffix(".manifest.json")
    manifest = None
    flags = []
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("MT5 feed manifest is not a JSON object")
        if manifest.get("bar_count") != len(bars):
            raise ValueError("Manifest bar count does not match research CSV")
        expected_open = manifest.get("last_open_utc")
        try:
            manifest_last = datetime.fromisoformat(str(expected_open).replace("Z","+00:00"))
        except (ValueError,TypeError) as error:
            raise ValueError("Manifest last_open_utc is malformed") from error
        if manifest_last != last:
            raise ValueError("Manifest latest bar does not match research CSV")
        if manifest.get("source") is None:
            raise ValueError("Manifest does not identify its source")
        flags.append("Broker server UTC offset not independently verified")
    else:
        flags.append("No adjacent feed provenance manifest; source unverified")
    if gap_count:
        flags.append("Observed candle gaps include possible market closures; do not fill automatically")
    lag = (clock - last_close).total_seconds()
    if lag > 180:
        flags.append("Last closed candle is older than 180 seconds; market-open state unknown")
    return {
        "status":"RESEARCH_FEED_ONLY",
        "input_csv_sha256":feed_sha256(path),
        "bar_count":len(bars),
        "first_open_utc":first.isoformat(),
        "last_open_utc":last.isoformat(),
        "last_close_utc":last_close.isoformat(),
        "seconds_since_last_close":round(lag),
        "gap_count":gap_count,
        "missing_minutes_between_observed_candles":missing_minutes,
        "longest_gap_missing_minutes":longest_gap,
        "source_manifest_present":manifest is not None,
        "source":manifest.get("source") if manifest else None,
        "symbol":manifest.get("symbol") if manifest else None,
        "broker_utc_offset_minutes":manifest.get("broker_utc_offset_minutes") if manifest else None,
        "broker_offset_independently_verified":False,
        "quote_quality":manifest.get("quote_quality") if manifest else "Unknown; may be chart OHLC only",
        "flags":flags,
        "note":"Observed M1 history is not proof of market openness, execution accuracy or strategy profitability.",
    }
