"""Read-only MT5 M1 candle exporter.

Run alongside a logged-in MetaTrader 5 terminal on a supported host.
NO account login, NO order_send and NO trade-management API calls.
The research scanner runs separately and reads the atomically written CSV.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .engine import Bar, read_m1

UTC = timezone.utc
HEADERS = ("timestamp", "open", "high", "low", "close")
MAX_BARS = 100_000


def convert_closed_rates(rates: Iterable[Any], now: datetime | None = None) -> list[Bar]:
    """Read MT5 named records with epoch-second bar OPEN timestamps.

    MT5 position 0 is the forming bar. Caller MUST request from position 1.
    Also enforce close <= UTC wall time as a defensive check.
    """
    now = (now or datetime.now(UTC)).astimezone(UTC)
    output = []
    for row in rates:
        stamp = datetime.fromtimestamp(int(row["time"]), UTC)
        if stamp.second or stamp.microsecond:
            raise ValueError("MT5 M1 candle timestamp not aligned to a UTC minute")
        if stamp + timedelta(minutes=1) > now:
            raise ValueError("MT5 returned a bar that has not completed yet")
        o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        if (not all(math.isfinite(p) and p > 0 for p in (o, h, l, c))
                or h < max(o, l, c) or l > min(o, h, c)):
            raise ValueError("Invalid MT5 OHLC values")
        output.append(Bar(stamp, o, h, l, c))
    output.sort(key=lambda bar: bar.time)
    if any(a.time >= b.time for a, b in zip(output, output[1:])):
        raise ValueError("Duplicate or out-of-order MT5 history timestamps")
    return output


def merge_immutable(existing: list[Bar], incoming: list[Bar]) -> list[Bar]:
    """Append unseen bars; never rewrite previously published closed candles."""
    if not incoming:
        raise ValueError("MT5 did not return completed candles")
    previous = {bar.time: bar for bar in existing}
    for bar in incoming:
        prior = previous.get(bar.time)
        if prior is not None:
            if prior.open_bid is not None:
                raise ValueError("Existing bid/ask OHLC feed cannot be overwritten by MT5 chart bars")
            if any(abs(getattr(prior, k)-getattr(bar, k)) > 1e-7
                   for k in ("open", "high", "low", "close")):
                raise ValueError(
                    "Historical closed candle revision detected. No automatic lookahead rewrite. "
                    "Review broker feed and archive before an explicit manual correction."
                )
        elif existing and bar.time < existing[-1].time:
            raise ValueError("Backfilling historical gaps requires an explicit offline validation")
        else:
            previous[bar.time] = bar
    return sorted(previous.values(), key=lambda bar: bar.time)


def _replace_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent,
            prefix=".xaubot-", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def store_feed(path: Path, bars: list[Bar], symbol: str,
               now: datetime | None = None) -> dict:
    """Validate and atomically publish both CSV and adjacent provenance manifest."""
    now = now or datetime.now(UTC)
    if not symbol or any(c in symbol for c in ("/", "\\", "\n", "\r")):
        raise ValueError("Unsafe or empty MT5 symbol")
    manifest_path = path.with_suffix(".manifest.json")
    if manifest_path.exists():
        details = json.loads(manifest_path.read_text(encoding="utf-8"))
        if details.get("symbol") != symbol:
            raise ValueError("Feed manifest belongs to another MT5 symbol")
    existing = read_m1(path) if path.exists() else []
    merged = merge_immutable(existing, bars)
    from io import StringIO
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADERS)
    for b in merged:
        writer.writerow((b.time.isoformat().replace("+00:00", "Z"), b.open, b.high, b.low, b.close))
    _replace_text_atomic(path, buffer.getvalue())
    status = {
        "source": "MetaTrader5.copy_rates_from_pos, start_pos=1 (completed M1)",
        "symbol": symbol,
        "bar_count": len(merged),
        "last_open_utc": merged[-1].time.isoformat(),
        "last_close_utc": (merged[-1].time + timedelta(minutes=1)).isoformat(),
        "published_utc": now.isoformat(),
        "quote_quality": "MT5 chart candles only; NOT genuine bid/ask OHLC",
        "mutability": "append-only; conflicting historical revisions raise an error",
    }
    _replace_text_atomic(manifest_path, json.dumps(status, indent=2) + "\n")
    return status


def fetch_mt5_closed(mt5: Any, symbol: str, count: int,
                     now: datetime | None = None) -> list[Bar]:
    """Only MT5 price-history reads. Position zero is never sampled."""
    if count < 1 or count > MAX_BARS:
        raise ValueError(f"count must be 1..{MAX_BARS}")
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, count)
    if rates is None or len(rates) == 0:
        raise RuntimeError("MetaTrader5 M1 history unavailable (check Market Watch and Max bars in chart)")
    return convert_closed_rates(rates, now)


def run_export(mt5: Any, symbol: str, out: Path, initial: int,
               overlap: int, once: bool, poll: int) -> None:
    if not symbol.strip() or initial < 1 or initial > MAX_BARS or overlap < 2 or poll < 5:
        raise ValueError("Invalid symbol or exporter parameters")
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError("MT5 symbol unavailable: select exact broker symbol")
    while True:
        try:
            if out.exists():
                existing = read_m1(out)
                age = max(0, int((datetime.now(UTC)-existing[-1].time).total_seconds()/60))
                requested = min(MAX_BARS, max(overlap, age + overlap))
            else:
                requested = initial
            bars = fetch_mt5_closed(mt5, symbol, requested)
            status = store_feed(out, bars, symbol)
            print(f"MT5 M1 export: {status['symbol']} candles={status['bar_count']} "
                  f"last_close={status['last_close_utc']}", flush=True)
        except (ValueError, RuntimeError, OSError) as exc:
            # Never log terminal credentials or broker account data.
            print(f"MT5 export failed: {type(exc).__name__}: {exc}", flush=True)
            if once:
                raise
        if once:
            return
        time.sleep(poll)


def main() -> None:
    p = argparse.ArgumentParser(description="Read-only completed-M1 exporter for an existing MT5 terminal")
    p.add_argument("--symbol", required=True, help="Exact broker symbol, e.g. XAUUSD or XAUUSDm")
    p.add_argument("--out", type=Path, default=Path("data/xauusd_m1.csv"))
    p.add_argument("--terminal-path", help="Optional existing MT5 terminal executable")
    p.add_argument("--initial-bars", type=int, default=30000)
    p.add_argument("--overlap-bars", type=int, default=120)
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--once", action="store_true")
    a = p.parse_args()
    try:
        import MetaTrader5 as mt5  # optional, installed on a machine running the MT5 terminal
    except ImportError as exc:
        p.error("MetaTrader5 package missing; install it where the MT5 terminal is installed")
        raise AssertionError from exc
    initialized = mt5.initialize(a.terminal_path) if a.terminal_path else mt5.initialize()
    if not initialized:
        p.error("MT5 terminal not reachable. Log into terminal manually and verify terminal path.")
    try:
        run_export(mt5, a.symbol, a.out, a.initial_bars, a.overlap_bars, a.once, a.poll)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
