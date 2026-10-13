"""Read-only human-readable research summaries for the Discord slash-command UI."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .engine import FAMILIES, strategies

UTC = timezone.utc


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _utc(s: str | None) -> datetime | None:
    try:
        if not s:
            return None
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except ValueError:
        return None


def status_report(root: Path, now: datetime | None = None) -> str:
    """Report source freshness from completed candle timestamps, not last file edit."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    scan = _read(root / "candidates.json")
    manifest = _read(root / "xauusd_m1.manifest.json")
    if scan is None:
        scan_status = "Scanner: no candidate journal yet"
    else:
        candidates = scan.get("candidates", [])
        count = len(candidates) if isinstance(candidates, list) else 0
        scan_time = _utc(scan.get("generated_at"))
        age = int((now - scan_time).total_seconds()) if scan_time else None
        if age is None:
            health = "unknown"
        elif age < -60:
            health = "invalid future timestamp"
        elif age > 180:
            health = "STALE"
        else:
            health = "recent"
        scan_status = f"Scanner: {health}, {count} current candidate(s)"
    if manifest is None:
        feed_status = "MT5 feed: no provenance manifest available"
    else:
        close = _utc(manifest.get("last_close_utc"))
        if close:
            seconds = int((now-close).total_seconds())
            freshness = "FRESH" if 0 <= seconds <= 180 else "STALE / out of sync"
            feed_status = (f"MT5 {manifest.get('symbol','?')}: {freshness}, "
                           f"last M1 close {close.strftime('%Y-%m-%d %H:%M UTC')}")
        else:
            feed_status = "MT5 feed: last candle timestamp unavailable"
    return ("**XAUBOT | RESEARCH STATUS**\n"
            f"{scan_status}\n{feed_status}\n"
            "Trading: disabled (paper-only). AI: advisory only.")


def signals_report(root: Path) -> str:
    data = _read(root / "candidates.json")
    candidates = data.get("candidates") if data else None
    if not isinstance(candidates, list):
        return "No candidate journal available. Start the XAUUSD scanner."
    primary = [c for c in candidates if isinstance(c, dict) and c.get("strategy")=="GWS_PRIMARY"]
    if not primary:
        return "No current GWS_PRIMARY paper candidate in the most recent completed M5 scan."
    report = ["**XAUBOT | LATEST GWS PAPER CANDIDATES**"]
    for c in primary[:3]:
        side = c.get("side", "?")
        ref = c.get("ref_price","?")
        stop = c.get("stop","?")
        report.append(f"{side} @ {ref} | SL {stop} | UTC {c.get('timestamp','?')}\n"
                      f"Candidate ID: {c.get('event_id','?')}")
    report.append("Candidates only. Not broker fills or executable trading instructions.")
    return "\n".join(report)[:1900]


def leaderboard_report(root: Path, minimum_closed: int = 20, limit: int = 10) -> str:
    """No ranking until an adequate trade sample; never imply actual performance."""
    if minimum_closed < 1 or limit < 1:
        raise ValueError("Invalid leaderboard threshold")
    data = _read(root / "backtest.json")
    if data is None:
        return "No paper backtest available. Run xaubot backtest with your historical M1 CSV."
    accounts = data.get("strategies", [])
    if not isinstance(accounts, list):
        return "Paper backtest summary is malformed."
    eligible = [x for x in accounts if isinstance(x,dict) and
                isinstance(x.get("closed"),int) and x["closed"] >= minimum_closed and
                isinstance(x.get("pnl"),(float,int)) and
                isinstance(x.get("equity"),(float,int))]
    if not eligible:
        return (f"No strategies have at least {minimum_closed} fully closed theoretical "
                "paper trades yet. No statistically meaningful ranking is available.")
    # Sort by (percentage) net return, not absolute profit; equity is common in baseline.
    initial = data.get("metadata",{}).get("initial_equity",1000)
    try:
        initial = float(initial)
    except (TypeError,ValueError):
        initial = 1000
    if initial <= 0:
        return "Paper backtest initial equity is invalid."
    eligible.sort(key=lambda x: (x["equity"]/initial - 1),reverse=True)
    lines = [f"**XAUBOT | EXPERIMENTAL PAPER RANKING (min {minimum_closed} closed)**",
             "Results use historical simulation assumptions, not broker-verified returns."]
    for index, x in enumerate(eligible[:limit],1):
        roi = 100*(x["equity"]/initial - 1)
        lines.append(f"{index}. {x.get('strategy','unknown')}: {roi:+.2f}% "
                     f"| n={x['closed']} | DD={x.get('max_dd_pct','?')}%")
    lines.append("Unadjusted exploratory ranks; multiple-testing and out-of-sample checks pending.")
    return "\n".join(lines)[:1900]


def strategies_report() -> str:
    ids = strategies()
    return (f"**XAUBOT | STRATEGY REGISTRY**\n"
            f"{len(ids)} deterministic experimental configurations: "
            f"1 primary GWS-style hypothesis + 200 challengers across "
            f"{len(FAMILIES)} SMC families.\n"
            "None has yet established a validated trading edge.")
