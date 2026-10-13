"""Reproducible, point-in-time XAUUSD research data audit tests."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from xaubot.engine import read_m1
from xaubot.feed_audit import audit_feed, feed_sha256

UTC = timezone.utc
NOW = datetime(2026,10,13,21,15,tzinfo=UTC)


def sample_feed(path: Path, minutes: list[int]) -> None:
    with path.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.writer(handle)
        writer.writerow(("timestamp","open","high","low","close"))
        for minute in minutes:
            stamp=datetime(2026,10,13,21,minute,tzinfo=UTC)
            writer.writerow((stamp.isoformat().replace("+00:00","Z"),4160,4161,4159,4160.5))


def manifest(path: Path, count: int, last_minute: int) -> None:
    stamp=datetime(2026,10,13,21,last_minute,tzinfo=UTC)
    meta={"source":"MQL5 CopyRates(PERIOD_M1, position=1), FILE_COMMON, Wine",
          "symbol":"XAUUSD","bar_count":count,
          "broker_utc_offset_minutes":120,
          "last_open_utc":stamp.isoformat(),
          "quote_quality":"MT5 chart candles only; NOT genuine bid/ask OHLC"}
    path.with_suffix(".manifest.json").write_text(json.dumps(meta),encoding="utf-8")


class FeedAuditTests(unittest.TestCase):
    def test_provenance_hash_gaps_and_provisional_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"feed.csv"
            sample_feed(src,[0,1,4,5])
            manifest(src,4,5)
            result=audit_feed(src,now=NOW)
            self.assertEqual(result["input_csv_sha256"],feed_sha256(src))
            self.assertEqual(result["gap_count"],1)
            self.assertEqual(result["missing_minutes_between_observed_candles"],2)
            self.assertEqual(result["longest_gap_missing_minutes"],2)
            self.assertEqual(result["broker_utc_offset_minutes"],120)
            self.assertFalse(result["broker_offset_independently_verified"])
            self.assertEqual(result["source"],"MQL5 CopyRates(PERIOD_M1, position=1), FILE_COMMON, Wine")
            self.assertEqual(result["last_close_utc"],"2026-10-13T21:06:00+00:00")
            self.assertIn("unknown",result["flags"][-1].lower())

    def test_no_manifest_never_implies_verified_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"feed.csv"
            sample_feed(src,[0,1])
            result=audit_feed(src,now=NOW)
            self.assertFalse(result["source_manifest_present"])
            self.assertIsNone(result["broker_utc_offset_minutes"])
            self.assertTrue(any("No adjacent" in f for f in result["flags"]))

    def test_manifest_count_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"feed.csv"
            sample_feed(src,[0,1])
            manifest(src,4,1)
            with self.assertRaisesRegex(ValueError,"count"):
                audit_feed(src,now=NOW)

    def test_manifest_newest_timestamp_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"feed.csv"
            sample_feed(src,[0,1])
            manifest(src,2,2)
            with self.assertRaisesRegex(ValueError,"latest bar"):
                audit_feed(src,now=NOW)

    def test_future_candle_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"feed.csv"
            sample_feed(src,[0,1])
            with self.assertRaisesRegex(ValueError,"beyond UTC clock"):
                audit_feed(src,now=datetime(2026,10,13,21,0,tzinfo=UTC))

    def test_hash_changes_if_feed_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"feed.csv"
            sample_feed(src,[0,1])
            before=feed_sha256(src)
            sample_feed(src,[0,1,2])
            self.assertNotEqual(before,feed_sha256(src))

    def test_stale_candles_never_claim_market_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"feed.csv"
            sample_feed(src,[0,1])
            result=audit_feed(src,now=NOW)
            self.assertGreater(result["seconds_since_last_close"],180)
            self.assertTrue(any("market-open state unknown" in f for f in result["flags"]))


if __name__=="__main__":
    unittest.main()
