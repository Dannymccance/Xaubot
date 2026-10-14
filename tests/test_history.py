"""Historical snapshot conversion rejects unverified broker/DST ambiguity."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xaubot.engine import read_m1
from xaubot.history import import_archive, read_schedule

UTC=timezone.utc


def row(when,offset,price=4000.):
    stamp=int(when.timestamp())+60*offset
    return f"XAUUSD,{stamp},{price},{price+1},{price-1},{price+.25}\n"


class MT5HistoricalImporterTests(unittest.TestCase):
    def setUp(self):
        self.ctx=tempfile.TemporaryDirectory()
        self.addCleanup(self.ctx.cleanup)
        self.folder=Path(self.ctx.name)
        self.raw=self.folder/"xaubot_history_xauusd_m1_server.csv"
        self.schedule=self.folder/"offsets.json"
        self.out=self.folder/"archive.csv"
        one=datetime(2026,9,30,11,0,tzinfo=UTC)
        two=datetime(2026,10,10,11,0,tzinfo=UTC)
        self.times=(one,two)
        self.raw.write_text("symbol,server_epoch,open,high,low,close\n"
                            +row(one,120)+row(two,180))
        self.schedule.write_text(json.dumps({"segments":[
            {"from_server":"2026-01-01T00:00:00",
             "until_server":"2026-10-01T00:00:00","offset_minutes":120},
            {"from_server":"2026-10-01T00:00:00",
             "until_server":"2027-01-01T00:00:00","offset_minutes":180},
        ]}))

    def test_multiple_offsets_are_resolved_correctly_without_rewriting_live_feed(self):
        result=import_archive(self.raw,self.out,"XAUUSD",self.schedule,
                              now=datetime(2026,10,14,tzinfo=UTC))
        times=[b.time for b in read_m1(self.out)]
        self.assertEqual(times,list(self.times))
        self.assertEqual(result["bar_count"],2)
        self.assertTrue(result["history_archive"])
        self.assertFalse(result["offset_schedule_operator_attested"])
        self.assertFalse(result["broker_offset_independently_verified"])
        self.assertTrue(self.out.with_suffix(".manifest.json").exists())
        with self.assertRaisesRegex(ValueError,"already exists"):
            import_archive(self.raw,self.out,"XAUUSD",self.schedule)

    def test_missing_broker_segment_fails_closed(self):
        self.schedule.write_text(json.dumps({"segments":[{
            "from_server":"2026-01-01T00:00:00",
            "until_server":"2026-10-01T00:00:00",
            "offset_minutes":120,
        }]}))
        with self.assertRaisesRegex(ValueError,"No unambiguous"):
            import_archive(self.raw,self.out,"XAUUSD",self.schedule)
        self.assertFalse(self.out.exists())

    def test_ambiguous_duplicate_or_unsorted_time_fails_closed(self):
        one=datetime(2026,10,10,11,0,tzinfo=UTC)
        self.raw.write_text("symbol,server_epoch,open,high,low,close\n"
                            +row(one,180)+row(one,180))
        with self.assertRaisesRegex(ValueError,"non-monotonic"):
            import_archive(self.raw,self.out,"XAUUSD",self.schedule)

    def test_invalid_schedule_rejected(self):
        self.schedule.write_text(json.dumps({"segments":[
            {"from_server":"2026-01-01T00:00:00",
             "until_server":"2026-03-01T00:00:00","offset_minutes":120},
            {"from_server":"2026-03-02T00:00:00",
             "until_server":"2027-01-01T00:00:00","offset_minutes":180},
        ]}))
        with self.assertRaisesRegex(ValueError,"contiguous"):
            read_schedule(self.schedule)

    def test_historical_exporter_unique_and_trade_free(self):
        source=(Path(__file__).parents[1]/"mt5/XaubotHistorySnapshot.mq5").read_text()
        self.assertIn('InpRequestedBars=300000',source)
        self.assertIn('FileMove(tmp,FILE_COMMON,InpOutputName,FILE_COMMON|FILE_REWRITE)',source)
        self.assertIn('InpOutputName="xaubot_history_xauusd_m1_server.csv"',source)
        self.assertNotIn("OrderSend(",source)
        self.assertNotIn("CTrade",source)


if __name__=="__main__":
    unittest.main()
