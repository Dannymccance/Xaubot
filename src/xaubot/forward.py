"""Independent, forward-only XAUUSD candidate journal. No trading or broker APIs.

Records ONLY newly observed fresh completed M5 candidates after activation.
Historical observations, downtime and market closures never become 'live' signals.
This is signal collection, not paper trade fills or returns.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .engine import Bar, evaluate, read_m1, strategies
from .feed_audit import audit_feed

UTC = timezone.utc
VERSION = 1
FRESH_SECONDS = 180


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(UTC).isoformat()


def _parse_stamp(raw: str) -> datetime:
    stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise ValueError("Forward journal cursor is not UTC")
    return stamp.astimezone(UTC)


def _bar_marker(bar: Bar) -> dict:
    return {
        "time": _iso(bar.time),
        "open": bar.open, "high": bar.high,
        "low": bar.low, "close": bar.close,
    }


def _save_atomic(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".xaubot-forward-", suffix=".tmp", delete=False,
        ) as out:
            temp_name = out.name
            json.dump(state, out, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def read_journal(path: Path) -> dict:
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("version") != VERSION:
        raise ValueError("Unsupported forward journal schema")
    if state.get("mode") != "FORWARD_FRESH_CANDIDATES_ONLY":
        raise ValueError("Incorrect journal mode")
    if not isinstance(state.get("events"), list):
        raise ValueError("Malformed forward journal events")
    return state


def forward_once(csv_path: Path, state_path: Path, expected_offset_minutes: int,
                 *, offset_verified: bool,
                 now: datetime | None = None) -> dict:
    """Advance the journal from new observed bars, never from backtest history.

    Operator confirmation of the broker offset is mandatory, but is not an
    independent cryptographic or broker-provided verification.
    """
    if not offset_verified:
        raise ValueError("Broker UTC offset has not been independently checked. Do not start forward mode.")
    if not -14 * 60 <= expected_offset_minutes <= 14 * 60:
        raise ValueError("Invalid broker offset")
    csv_path, state_path = Path(csv_path), Path(state_path)
    if csv_path.resolve() == state_path.resolve():
        raise ValueError("Forward journal and M1 feed must be different files")
    clock = (now or datetime.now(UTC)).astimezone(UTC)
    bars = read_m1(csv_path)
    audit = audit_feed(csv_path, bars, clock)
    if not audit["source_manifest_present"] or audit["source"] is None:
        raise ValueError("Forward mode requires MT5 feed provenance manifest")
    if audit["symbol"] != "XAUUSD":
        raise ValueError("Forward mode requires an XAUUSD feed")
    if audit["broker_utc_offset_minutes"] != expected_offset_minutes:
        raise ValueError("Broker UTC offset does not match the expected independently checked value")
    latest_close = bars[-1].time + timedelta(minutes=1)
    if not state_path.exists():
        # First activation is a baseline, not retroactive paper trades or signals.
        state = {
            "version": VERSION, "mode": "FORWARD_FRESH_CANDIDATES_ONLY",
            "started_utc": _iso(clock), "source": audit["source"],
            "symbol": audit["symbol"],
            "broker_utc_offset_minutes": expected_offset_minutes,
            "offset_verification": "OPERATOR_ATTESTED_ONLY",
            "baseline_csv_sha256": audit["input_csv_sha256"],
            "baseline_last_close_utc": _iso(latest_close),
            "last_seen_close_utc": _iso(latest_close),
            "last_seen_bar": _bar_marker(bars[-1]),
            "observed_fresh_m5": 0, "skipped_stale_m5": 0,
            "events": [],
            "note": "Fresh candidates only. No fills, win rate, PnL or independent proof of strategy quality.",
        }
        _save_atomic(state_path, state)
        return {"initialized": True, "new_events": 0, "new_m5": 0,
                "skipped_stale_m5": 0, "last_seen_close_utc": _iso(latest_close)}
    state = read_journal(state_path)
    if (state.get("source") != audit["source"] or
            state.get("symbol") != audit["symbol"] or
            state.get("broker_utc_offset_minutes") != expected_offset_minutes):
        raise ValueError("Forward journal provenance changed; manual review required")
    prior_close = _parse_stamp(state["last_seen_close_utc"])
    if latest_close < prior_close:
        raise ValueError("Feed rewound behind the last recorded forward cursor")
    prior_open = prior_close - timedelta(minutes=1)
    existing = next((bar for bar in bars if bar.time == prior_open), None)
    if existing is None or _bar_marker(existing) != state["last_seen_bar"]:
        raise ValueError("Previously observed M1 cursor candle is missing or rewritten")
    if latest_close == prior_close:
        return {"initialized": False, "new_events": 0, "new_m5": 0,
                "skipped_stale_m5": 0, "last_seen_close_utc": _iso(prior_close)}
    fresh_m5 = 0
    skipped = 0
    new_events = 0
    known = {record["event_id"] for record in state["events"]}
    allowed_strategies = set(strategies())
    for index, bar in enumerate(bars):
        close = bar.time + timedelta(minutes=1)
        if close <= prior_close or bar.time.minute % 5 != 4:
            continue
        lag = (clock - close).total_seconds()
        if not 0 <= lag <= FRESH_SECONDS:
            # Especially after outages, do not count previously unobserved
            # historical signals as independent forward research observations.
            skipped += 1
            continue
        fresh_m5 += 1
        for cand in evaluate(bars[max(0, index + 1 - 18 * 1440):index + 1]):
            if cand.strategy not in allowed_strategies or cand.timestamp != close:
                continue
            if cand.event_id in known:
                continue
            state["events"].append({
                "event_id": cand.event_id,
                "kind": "FRESH_M5_CANDIDATE",
                "observed_at_utc": _iso(clock),
                "candidate": cand.to_dict(),
            })
            known.add(cand.event_id)
            new_events += 1
    state["last_seen_close_utc"] = _iso(latest_close)
    state["last_seen_bar"] = _bar_marker(bars[-1])
    state["observed_fresh_m5"] += fresh_m5
    state["skipped_stale_m5"] += skipped
    _save_atomic(state_path, state)
    return {"initialized": False, "new_events": new_events,
            "new_m5": fresh_m5, "skipped_stale_m5": skipped,
            "last_seen_close_utc": _iso(latest_close)}


def report(path: Path) -> dict:
    state = read_journal(path)
    counts: dict[str,int] = {}
    for row in state["events"]:
        name = row["candidate"]["strategy"]
        counts[name] = counts.get(name, 0) + 1
    return {
        "mode": state["mode"],
        "started_utc": state["started_utc"],
        "baseline_last_close_utc": state["baseline_last_close_utc"],
        "last_seen_close_utc": state["last_seen_close_utc"],
        "observed_fresh_m5": state["observed_fresh_m5"],
        "skipped_stale_m5": state["skipped_stale_m5"],
        "candidate_count": len(state["events"]),
        "distinct_strategies_with_candidates": len(counts),
        "candidates_per_strategy": counts,
        "broker_utc_offset_minutes": state["broker_utc_offset_minutes"],
        "offset_verification": state["offset_verification"],
        "warning": "Research forward signal journal only. No simulated fills, returns, or orders.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Xaubot forward-only signal research journal")
    parser.add_argument("--csv", type=Path, default=Path("data/xauusd_m1.csv"))
    parser.add_argument("--state", type=Path, default=Path("data/forward_journal.json"))
    parser.add_argument("--expected-offset-minutes", type=int)
    parser.add_argument("--offset-verified", action="store_true",
                        help="Explicit operator confirmation of independent broker UTC offset check")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll", type=int, default=30)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.report:
        try:
            print(json.dumps(report(args.state), indent=2))
        except (OSError, ValueError, KeyError) as err:
            parser.error(f"Cannot read forward journal: {err}")
        return
    if args.expected_offset_minutes is None or not args.offset_verified:
        parser.error("Starting forward research requires --expected-offset-minutes and --offset-verified AFTER independent broker clock check")
    if args.poll < 5:
        parser.error("--poll must be at least 5 seconds")
    while True:
        try:
            result = forward_once(args.csv, args.state, args.expected_offset_minutes,
                                  offset_verified=args.offset_verified)
            if result["initialized"] or result["new_events"] or result["new_m5"] or result["skipped_stale_m5"]:
                print("Xaubot forward:", json.dumps(result), flush=True)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as err:
            print(f"Xaubot forward: {type(err).__name__}: {err}", file=sys.stderr, flush=True)
            if not args.watch:
                raise SystemExit(1) from None
        if not args.watch:
            break
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
