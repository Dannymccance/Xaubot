"""Bridge a read-only MQL5/Wine CSV export into Xaubot's UTC M1 research feed.

Runs on Ubuntu Python without importing MetaTrader5 or trading with an account.
The operator MUST specify the broker server's UTC offset in minutes.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .engine import Bar
from .mt5_export import store_feed

UTC = timezone.utc
SOURCE = "MQL5 CopyRates(PERIOD_M1, position=1), FILE_COMMON, Wine"
REQUIRED = ("symbol", "server_epoch", "open", "high", "low", "close")


def parse_mql_csv(source: Path, symbol: str, broker_utc_offset_minutes: int,
                  now: datetime | None = None) -> list[Bar]:
    """Reject malformed/inconsistent feeds rather than silently manufacturing UTC."""
    if not -14 * 60 <= broker_utc_offset_minutes <= 14 * 60:
        raise ValueError("broker UTC offset must be within +/-14 hours")
    if not symbol or any(c in symbol for c in ("/", "\\", "\r", "\n", ",")):
        raise ValueError("invalid broker symbol")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    candles = []
    with source.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(REQUIRED):
            raise ValueError(f"Unexpected MQL5 CSV header, expected {','.join(REQUIRED)}")
        for line_number, row in enumerate(reader, 2):
            try:
                if any(value is None or value == "" for value in row.values()):
                    raise ValueError("missing value")
                if row["symbol"] != symbol:
                    raise ValueError("symbol mismatch: input cannot be merged into this symbol feed")
                server_epoch = int(row["server_epoch"])
                # Broker server clock may be offset from UTC; explicitly normalise.
                open_time = datetime.fromtimestamp(
                    server_epoch - broker_utc_offset_minutes * 60, UTC
                )
                if open_time.second or open_time.microsecond:
                    raise ValueError("broker server time not aligned to an M1 boundary")
                if open_time + timedelta(minutes=1) > now + timedelta(seconds=15):
                    raise ValueError("future or forming candle after UTC conversion; verify broker offset")
                o,h,l,c = (float(row[k]) for k in ("open","high","low","close"))
                if (not all(math.isfinite(p) and p > 0 for p in (o,h,l,c))
                    or h < max(o,l,c) or l > min(o,h,c)):
                    raise ValueError("invalid OHLC values")
                if candles and open_time <= candles[-1].time:
                    raise ValueError("timestamps not strictly increasing after UTC conversion")
                candles.append(Bar(open_time,o,h,l,c))
            except (ValueError, OverflowError, OSError) as exc:
                raise ValueError(f"MQL5 CSV row {line_number}: {exc}") from exc
    if not candles:
        raise ValueError("MQL5 CSV contained no completed M1 bars")
    return candles


def import_once(source: Path, out: Path, symbol: str,
                broker_utc_offset_minutes: int,
                now: datetime | None = None) -> dict:
    """Publish a broker-referenced UTC feed with strict source and offset checks."""
    if source.resolve() == out.resolve():
        raise ValueError("Source and output must be different files")
    if out.exists() and not out.with_suffix(".manifest.json").exists():
        raise ValueError("Existing target has no provenance manifest; archive it before bridging")
    candles = parse_mql_csv(source,symbol,broker_utc_offset_minutes,now)
    return store_feed(
        out,candles,symbol,now,
        source=SOURCE,broker_utc_offset_minutes=broker_utc_offset_minutes,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Read-only Wine MQL5 XAUUSD-to-UTC bridge")
    p.add_argument("--source",required=True,type=Path,
                   help="Actual xaumt5 Wine FILE_COMMON CSV file (find path using MT5 Experts log)")
    p.add_argument("--out",type=Path,default=Path("data/xauusd_m1.csv"))
    p.add_argument("--symbol",required=True)
    p.add_argument("--broker-utc-offset-minutes",required=True,type=int,
                   help="Broker server UTC offset, for example 0, 120, 180; NEVER guessed")
    p.add_argument("--watch",action="store_true")
    p.add_argument("--poll",type=int,default=30)
    args = p.parse_args()
    if args.poll < 5:
        p.error("--poll must be >=5")
    # Avoid processing the same MQL5 snapshot repeatedly.
    last_signature = None
    while True:
        try:
            st = args.source.stat()
            signature = (st.st_mtime_ns,st.st_size)
            if signature != last_signature:
                result = import_once(args.source,args.out,args.symbol,args.broker_utc_offset_minutes)
                last_signature = signature
                print(f"Wine M1 bridge: {result['symbol']} {result['bar_count']} closed bars; "
                      f"last UTC close {result['last_close_utc']}",flush=True)
            elif not args.watch:
                print("No new MQL5 CSV snapshot.",flush=True)
        except (OSError, ValueError) as exc:
            print(f"Wine M1 bridge: {type(exc).__name__}: {exc}",file=sys.stderr,flush=True)
            if not args.watch:
                raise SystemExit(1) from None
        if not args.watch:
            return
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
