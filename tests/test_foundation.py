import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xaubot.engine import Bar, Candidate, compress, evaluate, read_m1, strategies
from xaubot.runner import PaperPosition, once, quote, replay, settle

UTC = timezone.utc


def bars(n=15, start=datetime(2026, 10, 13, 10, tzinfo=UTC)):
    return [Bar(start + timedelta(minutes=i), 4160., 4161., 4159., 4160.2)
            for i in range(n)]


def idea(side=1):
    return Candidate(datetime(2026,10,13,10,5,tzinfo=UTC),
                     "GWS_PRIMARY","gws_replica",side,4160.,4158.,4161.,
                     4157.,4160.,4155.,4164.,4166.5,4172.,
                     "fallback_3R_hypothesis",50,"fixture","scalp")


class XauBotTests(unittest.TestCase):
    def test_201_unique_strategies(self):
        ids = strategies()
        self.assertEqual(len(ids),201)
        self.assertEqual(len(set(ids)),201)
        self.assertEqual(ids[0],"GWS_PRIMARY")

    def test_m5_only_when_complete(self):
        sample = bars(4)
        self.assertEqual(compress(sample,5,5),[])
        res = compress(bars(5),5,5)
        self.assertEqual(len(res),1)
        self.assertEqual(res[0].time, datetime(2026,10,13,10,5,tzinfo=UTC))
        self.assertEqual(len(compress(bars(9),5,5)),1)
        self.assertEqual(len(compress(bars(10),5,5)),2)

    def test_missing_m1_breaks_m5_bucket(self):
        sample = bars(5)
        sample.pop(2)
        self.assertEqual(compress(sample,5,4),[])

    def test_read_requires_explicit_utc_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"m1.csv"
            path.write_text("timestamp,open,high,low,close\n"
                            "2026-10-13T10:00:00Z,1,2,0.5,1.5\n")
            self.assertEqual(len(read_m1(path)),1)
            path.write_text("timestamp,open,high,low,close\n"
                            "2026-10-13T10:00:00,1,2,0.5,1.5\n")
            with self.assertRaises(ValueError):
                read_m1(path)

    def test_future_mutation_cannot_change_prior_signal(self):
        sample = bars(100)
        current = evaluate(sample[:95])
        mutated = sample[:95] + [Bar(b.time,4999,5001,4998,5000)
                                for b in sample[95:]]
        self.assertEqual(current,evaluate(mutated[:95]))

    def test_bid_ask_exit_is_correct(self):
        b = Bar(datetime(2026,10,13,10,tzinfo=UTC),
                10.,11.,9.,10.,9.8,10.8,8.8,9.8,10.2,11.2,9.2,10.2)
        self.assertEqual(quote(b,1,"open",.4),10.2)
        self.assertEqual(quote(b,-1,"open",.4),9.8)
        # BUY exit should use the broker's BID low; SELL uses ASK high.
        self.assertEqual(quote(b,1,"low",.4),8.8)
        self.assertEqual(quote(b,-1,"high",.4),11.2)

    def test_stop_wins_intrabar_ambiguity(self):
        pos = PaperPosition(idea(),4160.,4155.,1.0)
        b = Bar(datetime(2026,10,13,10,5,tzinfo=UTC),4160,4174,4150,4162)
        events = settle(pos,b,.4,.05,False)
        self.assertEqual(events[0][2],"SL_or_BE")
        self.assertEqual(pos.remaining,0)

    def test_no_trade_order_in_replay(self):
        report = replay(bars(20))
        self.assertEqual(report["metadata"]["strategy_count"],201)
        self.assertEqual(len(report["strategies"]),201)
        self.assertFalse(report["events"])
        self.assertEqual(report["metadata"]["mode"],"RESEARCH_PAPER_ONLY")

    def test_stale_send_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError,"Stale or future"):
                once(bars(15),True,Path(directory)/"state.json")


if __name__ == "__main__":
    unittest.main()
