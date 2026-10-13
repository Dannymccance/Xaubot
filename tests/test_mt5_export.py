import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from xaubot.engine import Bar, read_m1
from xaubot.mt5_export import convert_closed_rates, fetch_mt5_closed, merge_immutable, store_feed

UTC = timezone.utc
NOW = datetime(2026, 10, 13, 10, 10, tzinfo=UTC)


def rate(minute, price=4160.0):
    stamp = datetime(2026,10,13,10,minute,tzinfo=UTC)
    return {"time":int(stamp.timestamp()),"open":price,
            "high":price+1,"low":price-1,"close":price+.2}


class Mt5ExporterTests(unittest.TestCase):
    def test_closed_candles_are_sorted_and_timezone_aware(self):
        output = convert_closed_rates([rate(8),rate(7)], now=NOW)
        self.assertEqual([b.time.minute for b in output], [7,8])
        self.assertEqual(output[0].time.utcoffset(),timedelta(0))

    def test_rejects_forming_candle(self):
        with self.assertRaisesRegex(ValueError,"not completed"):
            convert_closed_rates([rate(10)],now=NOW)

    def test_mt5_excludes_position_zero_and_never_places_orders(self):
        mt5 = Mock()
        mt5.TIMEFRAME_M1 = "M1"
        mt5.copy_rates_from_pos.return_value = [rate(8)]
        output = fetch_mt5_closed(mt5,"XAUUSDm",10,now=NOW)
        self.assertEqual(len(output),1)
        mt5.copy_rates_from_pos.assert_called_once_with("XAUUSDm","M1",1,10)
        mt5.order_send.assert_not_called()

    def test_rejects_broker_history_mutation(self):
        existing = convert_closed_rates([rate(6),rate(7)],now=NOW)
        revised = convert_closed_rates([rate(7,4170)],now=NOW)
        with self.assertRaisesRegex(ValueError,"revision"):
            merge_immutable(existing,revised)

    def test_merges_with_overlap_without_duplicate(self):
        existing = convert_closed_rates([rate(6),rate(7)],now=NOW)
        latest = convert_closed_rates([rate(7),rate(8)],now=NOW)
        self.assertEqual([b.time.minute for b in merge_immutable(existing,latest)], [6,7,8])

    def test_atomic_csv_and_manifest_preserve_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"xauusd_m1.csv"
            a = convert_closed_rates([rate(6),rate(7)],now=NOW)
            status = store_feed(path,a,"XAUUSDm",now=NOW)
            self.assertEqual(status["bar_count"],2)
            newer = convert_closed_rates([rate(7),rate(8)],now=NOW)
            newer_status = store_feed(path,newer,"XAUUSDm",now=NOW)
            self.assertEqual(newer_status["bar_count"],3)
            self.assertEqual(len(read_m1(path)),3)
            self.assertTrue((Path(directory)/"xauusd_m1.manifest.json").exists())
            with self.assertRaisesRegex(ValueError,"another MT5 symbol"):
                store_feed(path,newer,"XAUUSD",now=NOW)

    def test_no_backfill_of_missing_earlier_candles(self):
        a = convert_closed_rates([rate(6),rate(8)],now=NOW)
        b = convert_closed_rates([rate(7)],now=NOW)
        with self.assertRaisesRegex(ValueError,"Backfilling"):
            merge_immutable(a,b)

    def test_invalid_quotes_or_price_rejected(self):
        bad = rate(8)
        bad["high"] = bad["low"] - 1
        with self.assertRaisesRegex(ValueError,"Invalid MT5 OHLC"):
            convert_closed_rates([bad],now=NOW)


if __name__ == "__main__":
    unittest.main()
