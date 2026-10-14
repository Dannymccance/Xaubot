"""Daily 200-variation optimizer and independent MT5 historical archive regression tests."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from xaubot.engine import Bar, Candidate
from xaubot.optimizer import (
    build_candidate_tape, completed_group_metrics, load_candidate_tape,
    run_daily, TapeVariantEvaluator, assess,
)
from xaubot.variants import (
    BASES, filter_fresh_m5, filtered_candidates, matches, registry,
)

UTC = timezone.utc
START = datetime(2026,10,12,8,0,tzinfo=UTC)


def candle(t,open_=4160.,close=4160.7):
    return Bar(t,open_,4161.,4159.,close)


def idea(t, name=BASES["ob"]):
    return Candidate(t,name,"ob_continuation",1,4160.,4158.,4161.,
                     4157.,4160.,4155.,4164.,4166.5,4172.,
                     "fallback_3R_hypothesis",50,"fixture","scalp")


def fixture_files(folder: Path,n=50):
    feed=folder/"frozen.csv"
    rows=["timestamp,open,high,low,close"]
    for i in range(n):
        # Alternate a narrow bearish M5 with a directional engulfing M5:
        # optimizer prefilter must see some genuine c1 base opportunities.
        if (i//5)%2 == 0:
            rows.append(f"{(START+timedelta(minutes=i)).isoformat()},4160.5,4160.8,4159.5,4160.4")
        else:
            rows.append(f"{(START+timedelta(minutes=i)).isoformat()},4160,4161,4159,4160.7")
    feed.write_text("\n".join(rows)+"\n",encoding="utf-8")
    (folder/"frozen.manifest.json").write_text(json.dumps({
        "source":"MQL5 read-only historical research snapshot",
        "symbol":"XAUUSD","broker_utc_offset_minutes":120,
        "bar_count":n,
        "last_open_utc":(START+timedelta(minutes=n-1)).isoformat(),
    }),encoding="utf-8")
    config={
        "dataset":str(feed),"cache":str(folder/"tape.json"),
        "state":str(folder/"lab.json"),
        "usd_per_gbp":1.325,"contract_oz_per_lot":100,
        "lot_min":.01,"lot_step":.01,
        "broker_offset_attested":False,
    }
    path=folder/"config.json"
    path.write_text(json.dumps(config))
    return config,path


class OptimizerTests(unittest.TestCase):
    def test_registry_exact_120_ob_80_fvg_interleaved(self):
        items=registry()
        self.assertEqual(len(items),200)
        self.assertEqual(len({x.name for x in items}),200)
        self.assertEqual(sum(v.base==BASES["ob"] for v in items),120)
        self.assertEqual(sum(v.base==BASES["fvg"] for v in items),80)
        self.assertEqual(items[0].base,BASES["ob"])
        self.assertEqual(items[1].base,BASES["fvg"])
        self.assertEqual(items[0].momentum,"any")
        self.assertEqual(items[1].momentum,"any")

    def test_variant_filters_really_modify_signal_selection(self):
        m5=candle(START+timedelta(minutes=5))
        previous=candle(START)
        cand=idea(m5.time)
        zero=registry()[0]
        self.assertTrue(matches(zero,cand,m5,previous))
        updated=filtered_candidates(zero,[cand],m5,previous)
        self.assertEqual(len(updated),1)
        self.assertNotEqual(updated[0].event_id,cand.event_id)
        self.assertEqual(updated[0].stop,cand.stop)
        self.assertEqual(updated[0].tp3,cand.tp3)
        self.assertFalse(matches(zero,idea(m5.time+timedelta(minutes=5)),m5,previous))
        hi_range=next(x for x in registry() if x.base==BASES["ob"] and
                      x.min_m5_range==5 and x.momentum=="any" and x.session=="all_utc")
        self.assertFalse(matches(hi_range,cand,m5,previous))
        # Relative body is (4160.7 - 4160) / (4161 - 4159) = 35%.
        body40=next(x for x in registry() if x.base==BASES["ob"] and
                    x.momentum=="body40" and x.min_m5_range==0 and x.session=="all_utc")
        self.assertFalse(matches(body40,cand,m5,previous))
        outside=next(x for x in registry() if x.base==BASES["ob"] and
                     x.session=="asia_utc" and x.momentum=="any" and x.min_m5_range==0)
        self.assertFalse(matches(outside,cand,m5,previous))

    def test_cache_and_one_per_day_ledgers(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            config,config_file=fixture_files(folder)
            def evaluator(history):
                return [idea(history[-1].time+timedelta(minutes=1))]
            with patch("xaubot.optimizer.evaluate",side_effect=evaluator):
                cache=build_candidate_tape(Path(config["dataset"]),
                                           Path(config["cache"]))
            self.assertGreater(cache["candidate_count"],0)
            now=datetime(2026,10,14,12,tzinfo=UTC)
            output=run_daily(config_file,now=now)
            self.assertEqual(output["tested_count"],1)
            self.assertEqual(output["remaining"],199)
            self.assertEqual(output["status"],"PROVISIONAL_OFFSET_UNVERIFIED")
            self.assertEqual(output["stress_closed_groups"],0)
            self.assertEqual(run_daily(config_file,now=now)["status"],"ALREADY_RAN_TODAY")
            next_day=run_daily(config_file,now=now+timedelta(days=1))
            self.assertEqual(next_day["tested_count"],2)
            record=json.loads(Path(config["state"]).read_text())
            self.assertEqual(record["results"][0]["definition"]["base"],BASES["ob"])
            self.assertEqual(record["results"][1]["definition"]["base"],BASES["fvg"])
            self.assertEqual(record["paper_forward_shortlist"],[])
            # A different feed is a new research epoch, not silently mixed.
            Path(config["dataset"]).write_text(
                Path(config["dataset"]).read_text()+"\n")
            with self.assertRaises(ValueError):
                run_daily(config_file,now=now+timedelta(days=2))

    def test_cache_is_immutable_and_engine_hash_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,_=fixture_files(Path(tmp))
            with patch("xaubot.optimizer.evaluate",return_value=[]):
                build_candidate_tape(Path(config["dataset"]),Path(config["cache"]))
            with self.assertRaisesRegex(ValueError,"already exists"):
                build_candidate_tape(Path(config["dataset"]),Path(config["cache"]))
            with self.assertRaisesRegex(ValueError,"Stale/mismatched"):
                load_candidate_tape(Path(config["cache"]),"not-the-dataset-hash")

    def test_group_metrics_count_only_three_completed_legs(self):
        name="fixture"
        events=[
            {"type":"PAPER_OPEN_THREE_LEGS","strategy":name,"idea":"a",
             "planned_risk_gbp":10},
            {"type":"PAPER_TP1","strategy":name,"idea":"a","leg":"TP1",
             "realised_pnl_gbp":5,"time":"2026-10-13T10:05:00+00:00"},
            {"type":"PAPER_TP2","strategy":name,"idea":"a","leg":"TP2",
             "realised_pnl_gbp":2,"time":"2026-10-13T10:06:00+00:00"},
            {"type":"PAPER_TP3","strategy":name,"idea":"a","leg":"TP3",
             "realised_pnl_gbp":3,"time":"2026-10-13T10:07:00+00:00"},
            {"type":"PAPER_OPEN_THREE_LEGS","strategy":name,"idea":"b",
             "planned_risk_gbp":10},
            {"type":"PAPER_TP1","strategy":name,"idea":"b","leg":"TP1",
             "realised_pnl_gbp":1,"time":"2026-10-13T10:08:00+00:00"},
        ]
        report=completed_group_metrics(events,name)
        self.assertEqual(report["closed_groups"],1)
        self.assertEqual(report["expectancy_r"],1.)
        self.assertEqual(report["total_realised_pnl_gbp"],11.)
        self.assertEqual(report["completed_group_pnl_gbp"],10.)

    def test_in_sample_status_requires_time_and_offset(self):
        stats={
            "normal":{"closed_groups":80,"expectancy_r":.12},
            "stressed":{"closed_groups":75,"expectancy_r":.07,
                        "weeks_with_exits":13,"max_dd_pct":8.,
                        "pnl_excluding_best_week_gbp":100,
                        "positive_weeks":10},
        }
        self.assertEqual(assess(stats,240,False),"PROVISIONAL_OFFSET_UNVERIFIED")
        self.assertEqual(assess(stats,30,True),"INSUFFICIENT_HISTORICAL_COVERAGE")
        self.assertEqual(assess(stats,240,True),
                         "SHORTLIST_FOR_INDEPENDENT_FORWARD_PAPER_TEST")


if __name__=="__main__":
    unittest.main()
