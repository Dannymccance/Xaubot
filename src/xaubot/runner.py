"""Paper-only replay and CSV polling. Absolutely no MT5 order_send path."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .engine import Bar, Candidate, evaluate, read_m1, strategies
from .integrations import ai_commentary, send_discord, send_discord_test
from .reporting import leaderboard_report, signals_report, status_report, strategies_report
from .feed_audit import audit_feed, feed_sha256

UTC = timezone.utc


@dataclass
class PaperPosition:
    candidate: Candidate
    entry: float
    stop: float
    ounces: float        # theoretical, NOT a broker-valid lot size
    remaining: float = 1.0
    hit_tp1: bool = False
    hit_tp2: bool = False


def quote(b: Bar, side: int, kind: str, spread: float) -> float:
    if kind == "open":
        exact = b.open_ask if side == 1 else b.open_bid
        return exact if exact is not None else b.open + side*spread/2
    if kind == "high":
        exact = b.high_bid if side == 1 else b.high_ask
        return exact if exact is not None else b.high - side*spread/2
    if kind == "low":
        exact = b.low_bid if side == 1 else b.low_ask
        return exact if exact is not None else b.low - side*spread/2
    raise ValueError("unknown price kind")


def settle(pos: PaperPosition, b: Bar, spread: float, slippage: float, be_after_tp1: bool):
    """Stop first on ambiguous M1 bar. Closes use appropriate bid/ask side."""
    side = pos.candidate.side
    # A BUY closes at bid, a SELL at ask; adverse side is -side.
    qlow = quote(b, side, "low", spread)
    qhigh = quote(b, side, "high", spread)
    stop_hit = qlow <= pos.stop if side == 1 else qhigh >= pos.stop
    events = []
    if stop_hit:
        px = pos.stop - side*slippage
        events.append((pos.remaining, px, "SL_or_BE"))
        pos.remaining = 0
        return events
    for take, fraction, label in ((pos.candidate.tp1,.30,"TP1"),
                                   (pos.candidate.tp2,.30,"TP2"),
                                   (pos.candidate.tp3,.40,"TP3")):
        if label == "TP1" and pos.hit_tp1 or label == "TP2" and pos.hit_tp2:
            continue
        if pos.remaining <= 0:
            break
        high_enough = qhigh >= take if side == 1 else qlow <= take
        if not high_enough:
            continue
        qty = min(fraction, pos.remaining)
        events.append((qty, take - side*slippage, label))
        pos.remaining -= qty
        if label == "TP1":
            pos.hit_tp1 = True
            if be_after_tp1:
                pos.stop = pos.entry
        elif label == "TP2":
            pos.hit_tp2 = True
    return events


def replay(bars: list[Bar], spread: float = .4, slippage: float = .05,
           initial_equity: float = 1000., risk_fraction: float = .005,
           be_after_tp1: bool = False) -> dict:
    """Isolated abstract-oz portfolios. No broker-min-lot feasibility assumed."""
    if not (initial_equity > 0 and 0 < risk_fraction <= .02 and spread >= 0 and slippage >= 0):
        raise ValueError("invalid paper simulation parameters")
    names = strategies()
    accounts = {s: {"equity":initial_equity,"peak":initial_equity,"max_dd_pct":0.,
                    "signals":0,"trades":0,"closed":0,"wins":0,"pnl":0.} for s in names}
    opened: dict[str,PaperPosition] = {}
    pending: dict[str,Candidate] = {}
    cooldown: dict[str,datetime] = {}
    events = []
    for index, bar in enumerate(bars):
        for name, cand in list(pending.items()):
            if cand.timestamp != bar.time:
                if cand.timestamp < bar.time:
                    del pending[name]
                continue
            del pending[name]
            account = accounts[name]
            entry = quote(bar,cand.side,"open",spread) + cand.side*slippage
            risk_per_oz = (entry-cand.stop)*cand.side
            if risk_per_oz <= 0 or (cand.tp1-entry)*cand.side <= 0:
                continue
            risk_budget = account["equity"] * risk_fraction
            ounces = risk_budget / risk_per_oz
            opened[name] = PaperPosition(cand,entry,cand.stop,ounces)
            account["trades"] += 1
            events.append({"type":"OPEN","strategy":name,"time":bar.time.isoformat(),
                           "entry":entry,"idea":cand.event_id,
                           "theoretical_oz":ounces,"risk_usd":risk_budget})
        for name, position in list(opened.items()):
            account = accounts[name]
            for qty, exit_px, reason in settle(position,bar,spread,slippage,be_after_tp1):
                pnl = (exit_px-position.entry)*position.candidate.side*position.ounces*qty
                account["equity"] += pnl
                account["pnl"] += pnl
                account["peak"] = max(account["peak"],account["equity"])
                account["max_dd_pct"] = max(account["max_dd_pct"],
                            (account["peak"]-account["equity"])/account["peak"]*100)
                events.append({"type":reason,"strategy":name,"time":bar.time.isoformat(),
                               "idea":position.candidate.event_id,"realised_pnl":round(pnl,4)})
            if position.remaining < 1e-6:
                account["closed"] += 1
                # Realised winner count derived at idea close from all exit events.
                idea_pnl = sum(e.get("realised_pnl",0) for e in events
                               if e.get("strategy")==name and e.get("idea")==position.candidate.event_id)
                account["wins"] += int(idea_pnl > 0)
                del opened[name]
        if bar.time.minute % 5 != 4:
            continue
        # Only last 18 days needed for rolling technical snapshot. Never use future bars.
        proposed = evaluate(bars[max(0,index+1-18*1440):index+1])
        for cand in proposed:
            name = cand.strategy
            if name in opened or name in pending:
                continue
            if name in cooldown and cand.timestamp - cooldown[name] < timedelta(minutes=50):
                continue
            cooldown[name] = cand.timestamp
            pending[name] = cand
            accounts[name]["signals"] += 1
    scoreboard = [
        {"strategy":name,**{key:round(value,5) if isinstance(value,float) else value
                             for key,value in row.items()},
         "open_positions":int(name in opened)}
        for name,row in accounts.items()
    ]
    return {"metadata":{"mode":"RESEARCH_PAPER_ONLY","strategy_count":len(names),
                        "input_bar_count":len(bars),"initial_equity":initial_equity,
                        "spread_assumption":spread,
                        "slippage_assumption":slippage,"be_after_tp1":be_after_tp1,
                        "note":"Abstract ounces, no commission, swaps, minimum lot or broker fills; not deployable PnL"},
            "strategies":scoreboard,"events":events}


def _write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    temp.replace(path)


def once(bars: list[Bar], send: bool, state_path: Path, freshness: int = 180) -> list[dict]:
    candidates = evaluate(bars[-18*1440:])
    result = [c.to_dict() for c in candidates]
    if not send:
        return result
    # Feed timestamp marks start of last full M1; strictly require fresh completed bar.
    lag = (datetime.now(UTC) - (bars[-1].time+timedelta(minutes=1))).total_seconds()
    if lag < -60 or lag > freshness:
        raise RuntimeError(f"Stale or future M1 input: last bar closed {round(lag)}s ago")
    seen: list[str] = []
    if state_path.exists():
        prior = json.loads(state_path.read_text(encoding="utf-8"))
        seen = list(prior.get("seen",[]))
    for c in candidates:
        if c.strategy != "GWS_PRIMARY" or c.event_id in seen:
            continue
        # Only near-real-time alerts; never rebroadcast old historical candidates.
        if abs((datetime.now(UTC)-c.timestamp).total_seconds()) > 360:
            continue
        send_discord(c,ai_commentary(c))
        seen.append(c.event_id)
        # Persist successful sends immediately to survive process restarts.
        _write_json_atomic(state_path,{"seen":seen[-10000:]})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Xaubot paper-only XAUUSD research engine")
    sub = parser.add_subparsers(dest="command",required=True)
    sc = sub.add_parser("scan",help="inspect latest closed M5 bar")
    sc.add_argument("--csv",required=True,type=Path)
    sc.add_argument("--out",type=Path)
    sc.add_argument("--send-discord",action="store_true")
    sc.add_argument("--state",type=Path,default=Path("data/discord_seen.json"))
    sc.add_argument("--watch",action="store_true")
    sc.add_argument("--poll",type=int,default=30)
    aud = sub.add_parser("audit",help="audit UTC M1 input, provenance and gaps without running a backtest")
    aud.add_argument("--csv",required=True,type=Path)
    aud.add_argument("--out",type=Path)
    bt = sub.add_parser("backtest",help="historical shadow portfolios, no orders")
    bt.add_argument("--csv",required=True,type=Path)
    bt.add_argument("--out",type=Path,default=Path("data/backtest.json"))
    bt.add_argument("--spread",type=float,default=.4)
    bt.add_argument("--slippage",type=float,default=.05)
    bt.add_argument("--equity",type=float,default=1000.)
    bt.add_argument("--risk",type=float,default=.005)
    bt.add_argument("--be-after-tp1",action="store_true")
    sub.add_parser("discord-test",help="send an explicit Discord bot connectivity test")
    rp = sub.add_parser("report",help="inspect saved paper research reports")
    rp.add_argument("kind",choices=("status","signals","leaderboard","strategies"))
    rp.add_argument("--data-dir",type=Path,default=Path("data"))
    reg = sub.add_parser("strategies",help="list primary and challengers")
    args = parser.parse_args()
    if args.command == "discord-test":
        try:
            send_discord_test()
        except RuntimeError:
            print("Discord bot test failed. Check token, channel ID and bot permissions.",file=sys.stderr)
            raise SystemExit(1) from None
        print("Discord bot test message accepted by Discord.")
        return
    if args.command == "report":
        reports = {"status":lambda:status_report(args.data_dir),
                   "signals":lambda:signals_report(args.data_dir),
                   "leaderboard":lambda:leaderboard_report(args.data_dir),
                   "strategies":strategies_report}
        print(reports[args.kind]())
        return
    if args.command == "strategies":
        print(json.dumps({"count":len(strategies()),"ids":strategies()},indent=2))
        return
    if args.command == "audit":
        bars = read_m1(args.csv)
        audit = audit_feed(args.csv,bars)
        if args.out:
            _write_json_atomic(args.out,audit)
        print(json.dumps(audit,indent=2))
        return
    if args.command == "backtest":
        bars = read_m1(args.csv)
        audit = audit_feed(args.csv,bars)
        result = replay(bars,args.spread,args.slippage,args.equity,args.risk,args.be_after_tp1)
        # The systemd bridge may append to the CSV during a long replay.
        # Never attribute a replay snapshot to an input SHA that has changed.
        if feed_sha256(args.csv) != audit["input_csv_sha256"]:
            raise SystemExit("M1 feed changed during replay: retry with a frozen CSV snapshot")
        result["metadata"]["feed_audit"] = audit
        _write_json_atomic(args.out,result)
        print(json.dumps({"output":str(args.out),"strategies":len(result["strategies"]),
                          "events":len(result["events"]),
                          "warning":result["metadata"]["note"]},indent=2))
        return
    if args.poll < 5:
        parser.error("--poll must be >= 5")
    while True:
        try:
            bars = read_m1(args.csv)
            result = once(bars,args.send_discord or os.getenv("XAUBOT_SEND_DISCORD","0") == "1",args.state)
            if args.out:
                _write_json_atomic(args.out,{"generated_at":datetime.now(UTC).isoformat(),
                                             "last_m1_open_utc":bars[-1].time.isoformat(),
                                             "last_m1_close_utc":(bars[-1].time+timedelta(minutes=1)).isoformat(),
                                             "candidates":result})
            if not args.watch:
                print(json.dumps(result,indent=2))
                break
        except (OSError,ValueError,RuntimeError,json.JSONDecodeError) as error:
            print(f"Xaubot scan error ({type(error).__name__}). Verify M1 feed, UTC timestamps and integration settings; URLs and secrets are not logged.",file=sys.stderr)
            if not args.watch:
                raise SystemExit(1) from error
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
