import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from xaubot.discord_commands import _snowflake
from xaubot.reporting import leaderboard_report, signals_report, status_report, strategies_report

NOW = datetime(2026,10,13,10,10,tzinfo=timezone.utc)


class ReportingTests(unittest.TestCase):
    def test_status_uses_m1_close_not_only_scanner_update(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"candidates.json").write_text(json.dumps({
                "generated_at":NOW.isoformat(),"candidates":[]}))
            (root/"xauusd_m1.manifest.json").write_text(json.dumps({
                "symbol":"XAUUSDm",
                "last_close_utc":(NOW-timedelta(hours=2)).isoformat()}))
            report = status_report(root, now=NOW)
            self.assertIn("Scanner: recent", report)
            self.assertIn("STALE", report)
            self.assertIn("Trading: disabled", report)

    def test_leaderboard_refuses_inadequate_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"backtest.json").write_text(json.dumps({
                "metadata":{"initial_equity":1000},
                "strategies":[{"strategy":"a","closed":2,"pnl":1000,"equity":2000}]}))
            self.assertIn("No strategies",leaderboard_report(root,minimum_closed=20))

    def test_leaderboard_uses_configured_initial_equity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"backtest.json").write_text(json.dumps({
                "metadata":{"initial_equity":2000},
                "strategies":[{"strategy":"example","closed":25,"pnl":200,
                               "equity":2200,"max_dd_pct":5.0}]}))
            report = leaderboard_report(root)
            self.assertIn("+10.00%",report)
            self.assertIn("experimental",report.lower())

    def test_signal_report_is_explicit_about_research(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"candidates.json").write_text(json.dumps({
                "candidates":[{"strategy":"GWS_PRIMARY","side":"BUY",
                               "ref_price":4170,"stop":4160,
                               "timestamp":NOW.isoformat(),"event_id":"abc"},
                              {"strategy":"challenger","side":"SELL"}]}))
            result = signals_report(root)
            self.assertIn("paper",result.lower())
            self.assertIn("abc",result)
            self.assertNotIn("challenger",result)

    def test_strategy_registry(self):
        self.assertIn("201",strategies_report())

    def test_discord_snowflake_rejects_bad_ids(self):
        with patch.dict(os.environ,{"DISCORD_CHANNEL_ID":"notanid"}):
            with self.assertRaises(RuntimeError):
                _snowflake("DISCORD_CHANNEL_ID")
        with patch.dict(os.environ,{"DISCORD_CHANNEL_ID":"123456789012345678"}):
            self.assertEqual(_snowflake("DISCORD_CHANNEL_ID"),123456789012345678)


if __name__ == "__main__":
    unittest.main()
