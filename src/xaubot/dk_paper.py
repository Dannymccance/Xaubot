"""DKCapital V2-inspired, GBP-denominated paper simulation for 201 Xaubot hypotheses.

Xaubot generates its own stops/targets. They are NEVER DKCapital provider
instructions. This research simulator has no broker orders, no Telegram close
routing, and no actual MT5 fills or native SL/TP confirmations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .engine import Bar, Candidate, evaluate, strategies

IOM = ZoneInfo("Europe/Isle_of_Man")
STOP_ORIGIN = "XAUBOT_GENERATED_HYPOTHESIS"
TARGET_ORIGIN = "XAUBOT_GENERATED_HYPOTHESIS"
LABELS = ("TP1", "TP2", "TP3")
WEIGHTS = (.30, .30, .40)


@dataclass(frozen=True)
class DKPaperSettings:
    # Explicit observed reference rate (USD per 1 GBP); not live historical FX.
    usd_per_gbp: float
    contract_oz_per_lot: float
    lot_min: float
    lot_step: float
    leverage: float = 200.0
    initial_gbp: float = 1000.0
    group_risk_cap_gbp: float = 75.0
    portfolio_risk_cap_gbp: float = 150.0
    padding_gbp_per_leg: float = 1.0
    spread_usd: float = .4
    slippage_usd: float = .05

    def __post_init__(self) -> None:
        fields = (self.usd_per_gbp, self.contract_oz_per_lot, self.lot_min,
                  self.lot_step, self.leverage, self.initial_gbp,
                  self.group_risk_cap_gbp, self.portfolio_risk_cap_gbp,
                  self.padding_gbp_per_leg, self.spread_usd, self.slippage_usd)
        if not all(math.isfinite(x) for x in fields):
            raise ValueError("All DKCapital paper input values must be finite")
        if not (self.usd_per_gbp > 0 and self.contract_oz_per_lot > 0
                and self.lot_min > 0 and self.lot_step > 0
                and 1 <= self.leverage <= 1000 and
                self.initial_gbp == 1000.0 and
                self.group_risk_cap_gbp == 75.0 and
                self.portfolio_risk_cap_gbp == 150.0
                and self.padding_gbp_per_leg >= 0
                and self.spread_usd >= 0 and self.slippage_usd >= 0):
            raise ValueError("Invalid DKCapital paper settings; GBP 1,000 with GBP 75/150 caps only")
        if self.lot_min > 100 or self.lot_step > 100:
            raise ValueError("Broker lot minimum or step is implausible")

    @property
    def min_units(self) -> int:
        return math.ceil(self.lot_min / self.lot_step - 1e-9)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class DKLeg:
    label: str
    lots: float
    tp: float
    stop: float
    open: bool = True


@dataclass
class DKGroup:
    candidate: Candidate
    entry: float
    legs: list[DKLeg]
    margin_gbp: float
    tp1_hit: bool = False
    realised_gbp: float = 0.0

    def active_legs(self) -> list[DKLeg]:
        return [leg for leg in self.legs if leg.open]


def _quote(bar: Bar, side: int, kind: str, spread: float) -> float:
    if kind == "open":
        value = bar.open_ask if side == 1 else bar.open_bid
        return value if value is not None else bar.open + side * spread / 2
    if kind == "low":
        value = bar.low_bid if side == 1 else bar.low_ask
        return value if value is not None else bar.low - side * spread / 2
    if kind == "high":
        value = bar.high_bid if side == 1 else bar.high_ask
        return value if value is not None else bar.high - side * spread / 2
    raise ValueError("Unknown quote type")


def _units_and_lots(balance_gbp: float, when: datetime, settings: DKPaperSettings) -> list[list[float]]:
    """Return permitted candidate allocations, biggest to smallest, each 3 legs."""
    # DKcapital sizing is from realised GBP BALANCE, not leveraged notional.
    complete_hundreds = math.floor(balance_gbp / 100 + 1e-9)
    allowed_lots = complete_hundreds * .01
    if when.astimezone(IOM).weekday() == 4:
        allowed_lots = min(allowed_lots, .03)
    max_units = math.floor(allowed_lots / settings.lot_step + 1e-9)
    minimum = settings.min_units
    if max_units < 3 * minimum:
        return []
    candidates = []
    for units in range(max_units, 3 * minimum - 1, -1):
        sizes = [minimum, minimum, minimum]
        for _ in range(units - 3 * minimum):
            # Greedy legal allocation approximates DK's 30/30/40 targets.
            # Equal shortfall is broken in favour of TP2 then TP1 if TP3
            # has already received its 40% share (e.g. GBP500: 1/2/2).
            index = max(range(3), key=lambda i: (WEIGHTS[i] * units - sizes[i], i))
            sizes[index] += 1
        candidates.append([round(x * settings.lot_step, 8) for x in sizes])
    return candidates


def _leg_risk_gbp(group: DKGroup, leg: DKLeg, settings: DKPaperSettings) -> float:
    if not leg.open:
        return 0.0
    # Gross liability, no profit offset from other BUY/SELL groups. At BE,
    # a slippage allowance and per-leg costs remain reserved.
    loss_usd_per_oz = max(0.0, (group.entry - leg.stop) * group.candidate.side)
    return (loss_usd_per_oz + settings.slippage_usd) * (
        leg.lots * settings.contract_oz_per_lot) / settings.usd_per_gbp + settings.padding_gbp_per_leg


def _risk_gbp(group: DKGroup, settings: DKPaperSettings) -> float:
    return sum(_leg_risk_gbp(group, leg, settings) for leg in group.legs)


def _reserved_margin_gbp(group: DKGroup) -> float:
    original = sum(leg.lots for leg in group.legs)
    current = sum(leg.lots for leg in group.active_legs())
    return group.margin_gbp * current / original if original else 0.0


def _stop_touched(group: DKGroup, leg: DKLeg, bar: Bar, settings: DKPaperSettings) -> bool:
    price = _quote(bar, group.candidate.side,
                   "low" if group.candidate.side == 1 else "high", settings.spread_usd)
    return price <= leg.stop if group.candidate.side == 1 else price >= leg.stop


def _tp_touched(group: DKGroup, leg: DKLeg, bar: Bar, settings: DKPaperSettings) -> bool:
    price = _quote(bar, group.candidate.side,
                   "high" if group.candidate.side == 1 else "low", settings.spread_usd)
    return price >= leg.tp if group.candidate.side == 1 else price <= leg.tp


def _close_leg(group: DKGroup, leg: DKLeg, bar: Bar, reason: str, settings: DKPaperSettings,
               account: dict, events: list[dict]) -> None:
    side = group.candidate.side
    if reason == "PAPER_SL_OR_BE":
        exit_quote = _quote(bar, side, "open", settings.spread_usd)
        stop_fill = min(leg.stop, exit_quote) if side == 1 else max(leg.stop, exit_quote)
        exit_price = stop_fill - side * settings.slippage_usd
    else:
        exit_price = leg.tp - side * settings.slippage_usd
    pnl_gbp = (exit_price - group.entry) * side * leg.lots * (
        settings.contract_oz_per_lot / settings.usd_per_gbp)
    leg.open = False
    group.realised_gbp += pnl_gbp
    account["balance"] += pnl_gbp
    account["pnl"] += pnl_gbp
    account["peak"] = max(account["peak"], account["balance"])
    if account["peak"] > 0:
        account["max_dd_pct"] = max(
            account["max_dd_pct"],
            100 * (account["peak"] - account["balance"]) / account["peak"],
        )
    events.append({
        "type": reason, "strategy": group.candidate.strategy,
        "idea": group.candidate.event_id, "leg": leg.label,
        "time": bar.time.isoformat(), "lots": leg.lots,
        "exit_price": round(exit_price, 6),
        "realised_pnl_gbp": round(pnl_gbp, 5),
        "fill_quality": "M1_SYNTHETIC_NOT_BROKER_CONFIRMED",
    })


def _settle_group(group: DKGroup, bar: Bar, settings: DKPaperSettings,
                  account: dict, events: list[dict]) -> None:
    # Conservative SL-first resolution of same-minute TP/SL ambiguity.
    for leg in group.active_legs():
        if _stop_touched(group, leg, bar, settings):
            _close_leg(group, leg, bar, "PAPER_SL_OR_BE", settings, account, events)

    first = group.legs[0]
    if first.open and _tp_touched(group, first, bar, settings):
        _close_leg(group, first, bar, "PAPER_TP1", settings, account, events)
        group.tp1_hit = True
        for leg in group.active_legs():
            if ((group.candidate.side == 1 and leg.stop < group.entry)
                    or (group.candidate.side == -1 and leg.stop > group.entry)):
                leg.stop = group.entry
                events.append({
                    "type": "PAPER_BE_AFTER_ASSUMED_TP1",
                    "strategy": group.candidate.strategy,
                    "idea": group.candidate.event_id, "leg": leg.label,
                    "time": bar.time.isoformat(), "stop": leg.stop,
                    "provenance": "M1_SYNTHETIC_TP1_NOT_BROKER_CONFIRMATION",
                })

    # A just-moved BE may also be touched during that same M1. Assuming it
    # was touched is conservative when the intrabar sequence is unknown.
    for leg in group.active_legs():
        if _stop_touched(group, leg, bar, settings):
            _close_leg(group, leg, bar, "PAPER_SL_OR_BE", settings, account, events)
        elif _tp_touched(group, leg, bar, settings):
            _close_leg(group, leg, bar, "PAPER_" + leg.label, settings, account, events)


def replay_dkcapital(bars: list[Bar], settings: DKPaperSettings,
                     *, strategy_ids: tuple[str,...] | None = None,
                     evaluate_candidates: Callable[[list[Bar]],list[Candidate]] | None = None) -> dict:
    """Run GBP research; optional one-variant evaluator for daily offline discovery.

    Original callers still evaluate ALL existing 201 strategies unchanged.
    """
    names = strategies() if strategy_ids is None else strategy_ids
    if not names or len(set(names)) != len(names):
        raise ValueError("Strategy IDs must be nonempty and unique")
    evaluate_fn = evaluate if evaluate_candidates is None else evaluate_candidates
    accounts = {
        name: {"strategy":name,"balance":settings.initial_gbp,"equity":settings.initial_gbp,
               "peak":settings.initial_gbp, "max_dd_pct":0., "pnl":0., "signals":0,
               "trades":0,"closed":0,"wins":0, "size_rejected":0,
               "risk_rejected":0,"margin_rejected":0,
               "peak_reserved_risk_gbp":0.,"peak_reserved_margin_gbp":0.}
        for name in names
    }
    groups: dict[str, dict[str, DKGroup]] = {name:{} for name in names}
    pending: dict[str,Candidate] = {}
    cooldown: dict[str,datetime] = {}
    events: list[dict] = []
    for index, bar in enumerate(bars):
        for name, cand in list(pending.items()):
            if cand.timestamp != bar.time:
                if cand.timestamp < bar.time:
                    del pending[name]
                continue
            del pending[name]
            acc = accounts[name]
            side = cand.side
            entry = _quote(bar, side, "open", settings.spread_usd) + side * settings.slippage_usd
            # Generated stops/targets do NOT satisfy DKcapital's separate
            # provider-stop requirement for actual Telegram-driven execution.
            targets = (cand.tp1, cand.tp2, cand.tp3)
            if (side not in (-1,1) or (entry - cand.stop) * side <= 0 or
                    any((tp-entry) * side <= 0 for tp in targets) or
                    any((targets[i+1]-targets[i]) * side < 0 for i in range(2))):
                acc["size_rejected"] += 1
                continue
            existing = list(groups[name].values())
            reserved_risk = sum(_risk_gbp(g,settings) for g in existing)
            reserved_margin = sum(_reserved_margin_gbp(g) for g in existing)
            accepted = None
            rejected_due_margin = False
            for volume in _units_and_lots(acc["balance"], bar.time, settings):
                legs = [DKLeg(label,lots,tp,cand.stop)
                        for label,lots,tp in zip(LABELS,volume,targets)]
                ounces = sum(volume) * settings.contract_oz_per_lot
                margin = entry * ounces / settings.leverage / settings.usd_per_gbp
                proposal = DKGroup(cand,entry,legs,margin)
                group_risk = _risk_gbp(proposal,settings)
                if (group_risk > settings.group_risk_cap_gbp + 1e-8
                        or group_risk + reserved_risk > settings.portfolio_risk_cap_gbp + 1e-8):
                    continue
                if margin + reserved_margin > acc["balance"] + 1e-8:
                    rejected_due_margin = True
                    continue
                accepted = proposal
                break
            if accepted is None:
                if not _units_and_lots(acc["balance"],bar.time,settings):
                    acc["size_rejected"] += 1
                    reason = "PAPER_LOT_REJECT"
                elif rejected_due_margin:
                    acc["margin_rejected"] += 1
                    reason = "PAPER_MARGIN_REJECT"
                else:
                    acc["risk_rejected"] += 1
                    reason = "PAPER_RISK_REJECT"
                events.append({"type":reason,"strategy":name,"idea":cand.event_id,
                               "time":bar.time.isoformat(),
                               "stop_origin":STOP_ORIGIN})
                continue
            groups[name][cand.event_id] = accepted
            acc["trades"] += 1
            acc["peak_reserved_risk_gbp"] = max(
                acc["peak_reserved_risk_gbp"],
                reserved_risk + _risk_gbp(accepted,settings))
            acc["peak_reserved_margin_gbp"] = max(
                acc["peak_reserved_margin_gbp"], reserved_margin+accepted.margin_gbp)
            events.append({
                "type":"PAPER_OPEN_THREE_LEGS","strategy":name,
                "idea":cand.event_id,"time":bar.time.isoformat(),
                "side":"BUY" if side==1 else "SELL",
                "entry_usd_per_oz":round(entry,6),
                "stop_usd_per_oz":cand.stop,"stop_origin":STOP_ORIGIN,
                "target_origin":TARGET_ORIGIN,
                "legs":[{"label":leg.label,"lots":leg.lots,"tp":leg.tp,
                         "stop":leg.stop} for leg in accepted.legs],
                "planned_risk_gbp":round(_risk_gbp(accepted,settings),5),
                "initial_margin_gbp":round(accepted.margin_gbp,5),
                "margin_model":"XAUUSD_NOTIONAL_DIVIDED_BY_200",
                "fill_quality":"M1_SYNTHETIC_NOT_BROKER_CONFIRMED",
            })
        for name, by_id in groups.items():
            acc = accounts[name]
            for group_id, group in list(by_id.items()):
                _settle_group(group,bar,settings,acc,events)
                if not group.active_legs():
                    acc["closed"] += 1
                    acc["wins"] += int(group.realised_gbp > 0)
                    del by_id[group_id]
        if bar.time.minute % 5 != 4:
            continue
        proposed = evaluate_fn(bars[max(0,index+1-18*1440):index+1])
        for cand in proposed:
            name = cand.strategy
            if name not in accounts or name in pending:
                continue
            if name in cooldown and cand.timestamp - cooldown[name] < timedelta(minutes=50):
                continue
            if cand.event_id in groups[name]:
                continue
            cooldown[name] = cand.timestamp
            pending[name] = cand
            accounts[name]["signals"] += 1
    scoreboard = []
    for name in names:
        acc = accounts[name]
        remaining = groups[name]
        row = {
            **acc, "equity":acc["balance"],
            "open_positions":len(remaining),
            "open_legs":sum(len(g.active_legs()) for g in remaining.values()),
            "reserved_stop_risk_gbp":sum(_risk_gbp(g,settings) for g in remaining.values()),
            "reserved_initial_margin_gbp":sum(_reserved_margin_gbp(g) for g in remaining.values()),
        }
        scoreboard.append({
            k:round(v,5) if isinstance(v,float) else v for k,v in row.items()
        })
    return {
        "metadata":{
            "mode":"DKCAPITAL_V2_INSPIRED_RESEARCH_PAPER_ONLY",
            "strategy_count":len(names), "input_bar_count":len(bars),
            "initial_equity":settings.initial_gbp,"account_currency":"GBP",
            "leverage":settings.leverage,"risk_model":"DKCAPITAL_GBP_3_LEG_INITIAL_MARGIN",
            "model_parameters":settings.as_dict(),
            "stop_origin":STOP_ORIGIN,"target_origin":TARGET_ORIGIN,
            "broker_verified":False,
            "note":"201 independent GBP paper portfolios. Generated Xaubot stops are NOT provider stops. No broker fills, historical FX series, margin liquidation, commissions, swaps, order routing, approved layers or provider exits. Exploratory only.",
        },
        "strategies":scoreboard, "events":events,
    }
