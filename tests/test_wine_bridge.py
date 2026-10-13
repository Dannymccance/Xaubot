import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xaubot.engine import read_m1
from xaubot.wine_bridge import import_once, parse_mql_csv

UTC = timezone.utc
NOW = datetime(2026, 10, 13, 22, tzinfo=UTC)
HEADER = "symbol,server_epoch,open,high,low,close\n"


def row(minute, offset=0, price=4160, symbol="XAUUSD"):
    utc = datetime(2026,10,13,21,minute,tzinfo=UTC)
    epoch = int(utc.timestamp()) + offset*60
    return f"{symbol},{epoch},{price},{price+1},{price-1},{price+.5}\n"


class WineBridgeTests(unittest.TestCase):
    def test_utc_offset_is_explicit_and_applied_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/"raw.csv"
            src.write_text(HEADER + row(3,120) + row(4,120),encoding="utf-8")
            data=parse_mql_csv(src,"XAUUSD",120,NOW)
            self.assertEqual(data[0].time,datetime(2026,10,13,21,3,tzinfo=UTC))
            self.assertEqual(data[-1].close,4160.5)

    def test_rejects_missing_or_wrong_symbol(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/"raw.csv"
            src.write_text(HEADER + row(3,symbol="XAUUSDm"),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"symbol mismatch"):
                parse_mql_csv(src,"XAUUSD",0,NOW)

    def test_rejects_partial_or_invalid_csv(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/"raw.csv"
            src.write_text(HEADER + "XAUUSD,12345,4,5\n",encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_mql_csv(src,"XAUUSD",0,NOW)
            src.write_text("bad,header\nXAUUSD,123\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"header"):
                parse_mql_csv(src,"XAUUSD",0,NOW)

    def test_rejects_future_bar_from_wrong_offset(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/"raw.csv"
            # 23:00 UTC after conversion is in the future relative to NOW 22:00.
            future=int(NOW.timestamp()) + 3600
            src.write_text(HEADER+f"XAUUSD,{future},1,2,0.5,1.5\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"future or forming"):
                parse_mql_csv(src,"XAUUSD",0,NOW)

    def test_append_only_and_manifest_offset_lock(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            src=folder/"raw.csv"
            output=folder/"xauusd_m1.csv"
            src.write_text(HEADER+row(3)+row(4),encoding="utf-8")
            first=import_once(src,output,"XAUUSD",0,NOW)
            self.assertEqual(first["broker_utc_offset_minutes"],0)
            self.assertEqual(len(read_m1(output)),2)
            src.write_text(HEADER+row(3)+row(4)+row(5),encoding="utf-8")
            second=import_once(src,output,"XAUUSD",0,NOW)
            self.assertEqual(second["bar_count"],3)
            with self.assertRaisesRegex(ValueError,"UTC offset"):
                import_once(src,output,"XAUUSD",60,NOW)

    def test_rejects_broker_historical_revision(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            src=folder/"raw.csv"
            output=folder/"xauusd_m1.csv"
            src.write_text(HEADER+row(3)+row(4),encoding="utf-8")
            import_once(src,output,"XAUUSD",0,NOW)
            src.write_text(HEADER+row(3,price=4200)+row(4),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"revision"):
                import_once(src,output,"XAUUSD",0,NOW)

    def test_existing_unmanaged_feed_must_be_archived(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            src=folder/"raw.csv"
            output=folder/"xauusd_m1.csv"
            src.write_text(HEADER+row(3),encoding="utf-8")
            output.write_text("timestamp,open,high,low,close\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"no provenance manifest"):
                import_once(src,output,"XAUUSD",0,NOW)


if __name__ == "__main__":
    unittest.main()
