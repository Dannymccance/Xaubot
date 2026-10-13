"""No-hindsight forward-only research journal regression tests."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from xaubot.engine import Candidate
from xaubot.forward import forward_once, read_journal, report

UTC = timezone.utc
START = datetime(2026, 10, 13, 18, 0, tzinfo=UTC)


def make_bars(path: Path, count: int, *,
              symbol: str = "XAUUSD", offset: int = 120,
              edited_index: int = -1) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("timestamp", "open", "high", "low", "close"))
        for i in range(count):
            stamp = START + timedelta(minutes=i)
            close = 4160.5 if i != edited_index else 4160.7
            writer.writerow((stamp.isoformat().replace("+00:00","Z"),
                             4160,4161,4159,close))
    manifest = {
        "bar_count": count,
        "last_open_utc": (START + timedelta(minutes=count-1)).isoformat(),
        "source": "MQL5 CopyRates(PERIOD_M1, position=1), FILE_COMMON, Wine",
        "symbol": symbol,
        "broker_utc_offset_minutes": offset,
        "quote_quality": "MT5 chart candles only; NOT genuine bid/ask OHLC",
    }
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest),encoding="utf-8")


def make_candidate(at: datetime) -> Candidate:
    return Candidate(
        timestamp=at, strategy="double_top_bottom__c3__t2",
        family="double_top_bottom", side=1, ref_price=4160.,
        zone_low=4159., zone_high=4161., entry_low=4158.,
        entry_high=4160., stop=4154., tp1=4164., tp2=4166.5,
        tp3=4178., tp3_source="test", score=50,
        rationale="synthetic test", regime="scalp",
    )


class ForwardJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.csv_path = Path(self.tmp.name)/"xauusd_m1.csv"
        self.state_path = Path(self.tmp.name)/"forward.json"
        make_bars(self.csv_path, 5)

    def run_step(self, clock, verified=True):
        return forward_once(self.csv_path, self.state_path, 120,
                            offset_verified=verified, now=clock)

    def test_requires_operator_offset_confirmation(self):
        with self.assertRaisesRegex(ValueError, "independently checked"):
            self.run_step(START + timedelta(minutes=5),verified=False)
        self.assertFalse(self.state_path.exists())

    def test_first_activation_only_sets_baseline(self):
        with patch("xaubot.forward.evaluate") as evaluator:
            out=self.run_step(START+timedelta(minutes=5,seconds=5))
            self.assertTrue(out["initialized"])
            evaluator.assert_not_called()
        state=read_journal(self.state_path)
        self.assertEqual(state["events"], [])
        self.assertEqual(state["baseline_last_close_utc"], (START+timedelta(minutes=5)).isoformat())
        self.assertEqual(state["offset_verification"],"OPERATOR_ATTESTED_ONLY")

    def test_records_only_new_fresh_m5_once(self):
        self.run_step(START+timedelta(minutes=5,seconds=5))
        make_bars(self.csv_path,10)
        candidate=make_candidate(START+timedelta(minutes=10))
        with patch("xaubot.forward.evaluate",return_value=[candidate]) as evaluator:
            result=self.run_step(START+timedelta(minutes=10,seconds=30))
            self.assertEqual(result["new_m5"],1)
            self.assertEqual(result["new_events"],1)
            self.assertEqual(evaluator.call_count,1)
        with patch("xaubot.forward.evaluate") as evaluator:
            again=self.run_step(START+timedelta(minutes=10,seconds=45))
            evaluator.assert_not_called()
            self.assertEqual(again["new_events"],0)
        snapshot=report(self.state_path)
        self.assertEqual(snapshot["candidate_count"],1)
        self.assertEqual(snapshot["distinct_strategies_with_candidates"],1)
        self.assertNotIn("pnl",snapshot)
        self.assertEqual(read_journal(self.state_path)["events"][0]["candidate"]["strategy"],
                         "double_top_bottom__c3__t2")

    def test_downtime_never_becomes_forward_signal(self):
        self.run_step(START+timedelta(minutes=5,seconds=5))
        make_bars(self.csv_path,15)
        with patch("xaubot.forward.evaluate") as evaluator:
            result=self.run_step(START+timedelta(minutes=25))
            self.assertEqual(result["skipped_stale_m5"],2)
            self.assertEqual(result["new_m5"],0)
            evaluator.assert_not_called()
        self.assertEqual(report(self.state_path)["candidate_count"],0)

    def test_offset_mismatch_rejected(self):
        make_bars(self.csv_path,5,offset=180)
        with self.assertRaisesRegex(ValueError,"does not match"):
            self.run_step(START+timedelta(minutes=5))

    def test_symbol_mismatch_rejected(self):
        make_bars(self.csv_path,5,symbol="XAUUSDm")
        with self.assertRaisesRegex(ValueError,"XAUUSD feed"):
            self.run_step(START+timedelta(minutes=5))

    def test_cursor_history_rewrite_rejected(self):
        self.run_step(START+timedelta(minutes=5,seconds=5))
        make_bars(self.csv_path,10,edited_index=4)
        with self.assertRaisesRegex(ValueError,"missing or rewritten"):
            self.run_step(START+timedelta(minutes=10,seconds=30))

    def test_feed_rewind_rejected(self):
        make_bars(self.csv_path,10)
        self.run_step(START+timedelta(minutes=10,seconds=5))
        make_bars(self.csv_path,5)
        with self.assertRaisesRegex(ValueError,"rewound"):
            self.run_step(START+timedelta(minutes=11))

    def test_missing_manifest_rejected(self):
        self.csv_path.with_suffix(".manifest.json").unlink()
        with self.assertRaisesRegex(ValueError,"requires MT5 feed provenance"):
            self.run_step(START+timedelta(minutes=5))

    def test_future_bar_rejected(self):
        with self.assertRaisesRegex(ValueError,"beyond UTC clock"):
            self.run_step(START+timedelta(minutes=4))


if __name__ == "__main__":
    unittest.main()
