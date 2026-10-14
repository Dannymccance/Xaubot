"""Offline OB/FVG discovery laboratory: one new variation per UTC day.

Cache base signal *candidates* once from immutable M1 history; daily
risk/reward replays consume the cache under DKCapital GBP paper rules.
No broker connection, no order submission, no Discord messages.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .dk_paper import DKPaperSettings, replay_dkcapital
from .engine import Bar, Candidate, compress, evaluate, read_m1
from .feed_audit import audit_feed, feed_sha256
from .variants import BASES, Variant, filtered_candidates, registry

UTC = timezone.utc
CACHE_VERSION = 1
STATE_VERSION = 1


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _engine_hash() -> str:
    return _hash_file(Path(__file__).with_name("engine.py"))


def _variant_hash() -> str:
    return _hash_file(Path(__file__).with_name("variants.py"))


def _json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",encoding="utf-8",dir=path.parent,
            prefix=".xaubot-lab-",suffix=".tmp",delete=False,
        ) as f:
            tmp = f.name
            json.dump(data,f,indent=2,allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def _candidate_record(candidate: Candidate) -> dict:
    row = asdict(candidate)
    row["timestamp"] = candidate.timestamp.isoformat()
    return row


def _candidate_from_record(row: dict) -> Candidate:
    data = dict(row)
    data["timestamp"] = datetime.fromisoformat(data["timestamp"])
    if data["timestamp"].utcoffset() != timedelta(0):
        raise ValueError("Candidate tape timestamp must be UTC")
    return Candidate(**data)


def build_candidate_tape(dataset: Path, tape_path: Path) -> dict:
    """Compute OB/FVG baseline hypotheses ONCE, from closed candles only.

    Cache is independent from account sizing; it never includes outcomes.
    This operation is expensive for multi-year minute histories.
    """
    if dataset.resolve() == tape_path.resolve():
        raise ValueError("Input and tape output paths must differ")
    if tape_path.exists():
        raise ValueError("Candidate tape already exists; never overwrite a historical research cache")
    bars = read_m1(dataset)
    audit = audit_feed(dataset,bars)
    if not audit["source_manifest_present"] or audit["symbol"] != "XAUUSD":
        raise ValueError("Candidate tape requires XAUUSD M1 provenance manifest")
    sha = audit["input_csv_sha256"]
    # Both frozen base models use confirmation c1: directional M5 engulfing
    # candle, with a larger body than the prior M5. Preselect exactly those
    # closed-bar times in O(n) before expensive H1/H4/D1 zone evaluation.
    # This is a necessary precondition, NOT a signal, so it cannot discard
    # any valid OB c1 t1 or FVG c1 t2 base candidate.
    completed_m5 = compress(bars,5,5)
    likely_closes = set()
    for prior, cur in zip(completed_m5,completed_m5[1:]):
        if cur.time-prior.time != timedelta(minutes=5):
            continue
        if (cur.low <= prior.low and cur.high >= prior.high and
                abs(cur.close-cur.open) > abs(prior.close-prior.open) and
                cur.close != cur.open):
            likely_closes.add(cur.time)
    candidate_rows = []
    for index, bar in enumerate(bars):
        if bar.time.minute % 5 != 4 or (
                bar.time+timedelta(minutes=1) not in likely_closes):
            continue
        current = evaluate(bars[max(0,index+1-18*1440):index+1])
        base = [c for c in current if c.strategy in BASES.values()]
        if base:
            candidate_rows.extend(_candidate_record(c) for c in base)
    if feed_sha256(dataset) != sha:
        raise ValueError("Historical M1 snapshot changed during candidate-cache construction")
    cache = {
        "version":CACHE_VERSION,
        "type":"IMMUTABLE_CLOSED_M5_BASE_CANDIDATE_TAPE",
        "feed_sha256":sha, "engine_sha256":_engine_hash(),
        "bars":len(bars),
        "first_open_utc":bars[0].time.isoformat(),
        "last_open_utc":bars[-1].time.isoformat(),
        "broker_utc_offset_independently_verified":False,
        "sources":list(BASES.values()),
        "candidates":candidate_rows,
        "note":"Two base Xaubot hypotheses only, no future bars, no simulated fills or returns.",
    }
    _json_atomic(tape_path,cache)
    return {"candidate_count":len(candidate_rows),"bars":len(bars),
            "feed_sha256":sha,"cache":str(tape_path)}


def load_candidate_tape(path: Path, dataset_sha: str) -> list[Candidate]:
    cache = json.loads(path.read_text(encoding="utf-8"))
    if (cache.get("version") != CACHE_VERSION or
            cache.get("type") != "IMMUTABLE_CLOSED_M5_BASE_CANDIDATE_TAPE" or
            cache.get("feed_sha256") != dataset_sha or
            cache.get("engine_sha256") != _engine_hash() or
            set(cache.get("sources",[])) != set(BASES.values())):
        raise ValueError("Stale/mismatched candidate tape or engine; rebuild for a NEW dataset epoch")
    return [_candidate_from_record(row) for row in cache["candidates"]]


class TapeVariantEvaluator:
    """Only reads candidates and M5 candles timestamped <= current replay clock."""
    def __init__(self,variant: Variant,tape: list[Candidate],bars: list[Bar]):
        self.variant = variant
        selected = defaultdict(list)
        for cand in tape:
            if cand.strategy == variant.base:
                selected[cand.timestamp].append(cand)
        self._selected = selected
        m5 = compress(bars,5,5)
        self._m5 = {b.time:(b,m5[i-1] if i and
                           m5[i-1].time == b.time-timedelta(minutes=5)
                           else None) for i,b in enumerate(m5)}

    def __call__(self, seen_m1: list[Bar]) -> list[Candidate]:
        timestamp = seen_m1[-1].time + timedelta(minutes=1)
        if timestamp not in self._selected or timestamp not in self._m5:
            return []
        current, prior = self._m5[timestamp]
        return filtered_candidates(
            self.variant,self._selected[timestamp],current,prior,
        )


def completed_group_metrics(events: list[dict], name: str) -> dict:
    groups: dict[str,dict] = {}
    week_pnl = defaultdict(float)
    for event in events:
        if event.get("strategy") != name:
            continue
        typ = event["type"]
        idea = event.get("idea")
        if typ == "PAPER_OPEN_THREE_LEGS":
            groups[idea] = {
                "risk":event["planned_risk_gbp"],"pnl":0.,
                "legs":set(),
            }
        elif "realised_pnl_gbp" in event and idea in groups:
            groups[idea]["pnl"] += event["realised_pnl_gbp"]
            groups[idea]["legs"].add(event["leg"])
            week = datetime.fromisoformat(event["time"]).strftime("%G-W%V")
            week_pnl[week] += event["realised_pnl_gbp"]
    completed = [g for g in groups.values()
                 if g["legs"] == {"TP1","TP2","TP3"} and g["risk"] > 0]
    r = [g["pnl"]/g["risk"] for g in completed]
    weekly = dict(sorted(week_pnl.items()))
    total = sum(weekly.values())
    largest = max(weekly.values(),default=0.)
    return {
        "closed_groups":len(completed),
        "win_rate_pct":round(100*sum(x>0 for x in r)/len(r),4) if r else None,
        "expectancy_r":round(sum(r)/len(r),6) if r else None,
        "average_win_r":round(sum(x for x in r if x>0)/max(1,sum(x>0 for x in r)),6) if r else None,
        "average_loss_r":round(sum(x for x in r if x<0)/max(1,sum(x<0 for x in r)),6) if r else None,
        "total_realised_pnl_gbp":round(total,5),
        "completed_group_pnl_gbp":round(sum(g["pnl"] for g in completed),5),
        "weeks_with_exits":len(weekly),
        "positive_weeks":sum(v>0 for v in weekly.values()),
        "pnl_excluding_best_week_gbp":round(total-largest,5),
        "weekly_pnl_gbp":{k:round(v,5) for k,v in weekly.items()},
    }


def evaluate_one_variant(variant: Variant, training: list[Bar],
                         tape: list[Candidate], config: dict) -> dict:
    output = {}
    for label,multiplier in (("normal",1.),("stressed",2.)):
        params = DKPaperSettings(
            usd_per_gbp=float(config["usd_per_gbp"]),
            contract_oz_per_lot=float(config["contract_oz_per_lot"]),
            lot_min=float(config["lot_min"]),lot_step=float(config["lot_step"]),
            leverage=200.,initial_gbp=1000.,
            spread_usd=.4*multiplier,slippage_usd=.05*multiplier,
        )
        evaluator = TapeVariantEvaluator(variant,tape,training)
        replay = replay_dkcapital(training,params,
                   strategy_ids=(variant.name,),evaluate_candidates=evaluator)
        row = replay["strategies"][0]
        stats = completed_group_metrics(replay["events"],variant.name)
        output[label] = {
            **stats,
            "pnl_gbp":row["pnl"],"max_dd_pct":row["max_dd_pct"],
            "risk_rejected":row["risk_rejected"],
            "margin_rejected":row["margin_rejected"],
            "size_rejected":row["size_rejected"],
            "open_groups":row["open_positions"],
        }
    return output


def assess(result: dict,history_days: float,offset_attested: bool) -> str:
    normal,stress = result["normal"],result["stressed"]
    if not offset_attested:
        return "PROVISIONAL_OFFSET_UNVERIFIED"
    if history_days < 180:
        return "INSUFFICIENT_HISTORICAL_COVERAGE"
    if (min(normal["closed_groups"],stress["closed_groups"]) < 30 or
            stress["weeks_with_exits"] < 8):
        return "INSUFFICIENT_SAMPLE"
    if (normal["expectancy_r"] is None or stress["expectancy_r"] is None
            or normal["expectancy_r"] <= 0 or stress["expectancy_r"] <= 0):
        return "FAILED_COST_ROBUSTNESS"
    if (stress["max_dd_pct"] > 15 or
            stress["pnl_excluding_best_week_gbp"] <= 0 or
            stress["positive_weeks"] / stress["weeks_with_exits"] < .6):
        return "FAILED_STABILITY"
    return "SHORTLIST_FOR_INDEPENDENT_FORWARD_PAPER_TEST"


def _config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()


def _rebuild_ranking(results: list[dict]) -> list[dict]:
    ranking = []
    for row in results:
        stats = row["stressed"]
        ranking.append({
            "variant":row["variant"],
            "status":row["status"],
            "stressed_expectancy_r":stats["expectancy_r"],
            "stressed_closed_groups":stats["closed_groups"],
            "stressed_pnl_gbp":stats["pnl_gbp"],
            "stressed_drawdown_pct":stats["max_dd_pct"],
            "stress_excluding_best_week_gbp":stats["pnl_excluding_best_week_gbp"],
        })
    ranking.sort(key=lambda x:(x["status"]=="SHORTLIST_FOR_INDEPENDENT_FORWARD_PAPER_TEST",
                               x["stressed_expectancy_r"] if x["stressed_expectancy_r"] is not None else -999,
                               x["stressed_closed_groups"]),reverse=True)
    return ranking


def run_daily(config_file: Path, *,now: datetime | None=None) -> dict:
    config = json.loads(config_file.read_text(encoding="utf-8"))
    needed = {"dataset","cache","state","usd_per_gbp","contract_oz_per_lot",
              "lot_min","lot_step","broker_offset_attested"}
    if not isinstance(config,dict) or needed-set(config):
        raise ValueError("Optimizer config is incomplete; explicit broker/GBP assumptions required")
    if type(config["broker_offset_attested"]) is not bool:
        raise ValueError("broker_offset_attested must be boolean")
    dataset,tape_path,state_path = (Path(config[key]) for key in
                                    ("dataset","cache","state"))
    if len({p.resolve() for p in (dataset,tape_path,state_path)}) != 3:
        raise ValueError("Dataset, tape and result ledger must be separate files")
    # Validate all financial inputs even for an already completed UTC day.
    DKPaperSettings(usd_per_gbp=float(config["usd_per_gbp"]),
                    contract_oz_per_lot=float(config["contract_oz_per_lot"]),
                    lot_min=float(config["lot_min"]),
                    lot_step=float(config["lot_step"]))
    state_path.parent.mkdir(parents=True,exist_ok=True)
    lock_path = state_path.with_suffix(state_path.suffix+".lock")
    clock = (now or datetime.now(UTC)).astimezone(UTC)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        bars = read_m1(dataset)
        audit = audit_feed(dataset,bars,clock)
        if not audit["source_manifest_present"] or audit["symbol"]!="XAUUSD":
            raise ValueError("Optimizer requires immutable XAUUSD M1 data and adjacent manifest")
        sha = audit["input_csv_sha256"]
        tape = load_candidate_tape(tape_path,sha)
        config_sha = _config_hash(config)
        epoch = {
            "feed_sha256":sha,"engine_sha256":_engine_hash(),
            "variant_logic_sha256":_variant_hash(),
            "paper_risk_engine_sha256":_hash_file(Path(__file__).with_name("dk_paper.py")),
            "optimizer_engine_sha256":_hash_file(Path(__file__)),
            "config_sha256":config_sha,
        }
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("version")!=STATE_VERSION or any(
                    state.get(k)!=v for k,v in epoch.items()):
                raise ValueError("Dataset, optimizer code or settings changed: start a NEW ledger epoch, never mix results")
        else:
            state = {
                **epoch,"version":STATE_VERSION,
                "mode":"ONE_NEW_VARIANT_PER_UTC_DAY_RESEARCH_ONLY",
                "started_utc":clock.isoformat(),"last_day":None,
                "next_index":0,"results":[],"ranking":[],
                "paper_forward_shortlist":[],
                "note":"Discovery ranking only. Fixed history, no broker fills, no orders, no live performance.",
            }
        if state["last_day"]==clock.date().isoformat():
            return {"status":"ALREADY_RAN_TODAY","next_index":state["next_index"]}
        all_variants=registry()
        if state["next_index"]>=len(all_variants):
            return {"status":"ALL_200_VARIANTS_EVALUATED",
                    "count":len(state["results"])}
        cutoff = max(1,int(len(bars)*.75))
        training = bars[:cutoff]
        age_days=(training[-1].time-training[0].time).total_seconds()/86400
        variant=all_variants[state["next_index"]]
        stats = evaluate_one_variant(variant,training,tape,config)
        status = assess(stats,age_days,config["broker_offset_attested"])
        record = {
            "variant":variant.name,"definition":variant.as_dict(),
            "evaluated_at_utc":clock.isoformat(),
            "training_last_open_utc":training[-1].time.isoformat(),
            "training_bars":len(training),"training_span_days":round(age_days,2),
            "future_holdout_bars_not_used":len(bars)-len(training),
            "normal":stats["normal"],"stressed":stats["stressed"],
            "status":status,
        }
        # Prevent output misattribution if an operator edited the frozen CSV.
        if feed_sha256(dataset)!=sha:
            raise ValueError("Frozen dataset changed during daily evaluation")
        state["results"].append(record)
        state["next_index"]+=1
        state["last_day"]=clock.date().isoformat()
        state["ranking"]=_rebuild_ranking(state["results"])
        state["paper_forward_shortlist"]=[
            r["variant"] for r in state["ranking"]
            if r["status"]=="SHORTLIST_FOR_INDEPENDENT_FORWARD_PAPER_TEST"
        ][:3]
        _json_atomic(state_path,state)
        return {
            "status":status,"tested_today":variant.name,
            "tested_count":len(state["results"]),
            "remaining":len(all_variants)-state["next_index"],
            "normal_expectancy_r":stats["normal"]["expectancy_r"],
            "stress_expectancy_r":stats["stressed"]["expectancy_r"],
            "stress_closed_groups":stats["stressed"]["closed_groups"],
            "currently_ranked_top3":state["ranking"][:3],
            "forward_shortlist":state["paper_forward_shortlist"],
            "warning":"In-sample development only; initial 201 selections have already seen parts of this period. No trade execution.",
        }


def main() -> None:
    parser=argparse.ArgumentParser(description="Networkless, read-only XAUUSD 200-variant discovery")
    sub=parser.add_subparsers(dest="cmd",required=True)
    cache=sub.add_parser("cache",help="Compute baseline candidate tape once from frozen dataset")
    cache.add_argument("--dataset",required=True,type=Path)
    cache.add_argument("--out",required=True,type=Path)
    daily=sub.add_parser("once",help="Run at most ONE new challenger per UTC day")
    daily.add_argument("--config",type=Path,
                       default=Path("/app/data/optimizer_config.json"))
    status=sub.add_parser("status",help="Read completed offline ranking")
    status.add_argument("--state",type=Path,
                        default=Path("/app/data/optimizer_lab.json"))
    args=parser.parse_args()
    try:
        if args.cmd=="cache":
            output=build_candidate_tape(args.dataset,args.out)
        elif args.cmd=="once":
            output=run_daily(args.config)
        else:
            state=json.loads(args.state.read_text(encoding="utf-8"))
            output={"mode":state["mode"],"tested":len(state["results"]),
                    "remaining":200-state["next_index"],
                    "ranked_top10":state["ranking"][:10],
                    "paper_forward_shortlist":state["paper_forward_shortlist"]}
        print(json.dumps(output,indent=2))
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
        parser.error(f"Discovery failed closed: {exc}")


if __name__=="__main__":
    main()
