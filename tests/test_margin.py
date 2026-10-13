"""Simplified 1:200 XAUUSD research margin regression tests.

Positions remain abstract ounces, not broker-valid lots. This tests an initial
margin gate only; it does not pretend to implement liquidation or margin calls.
"""
import math
import unittest
from unittest.mock import patch

from xaubot.runner import initial_margin_usd, replay
from test_foundation import bars, idea


class PaperLeverageTests(unittest.TestCase):
    def test_200_to_1_initial_margin_calculation(self):
        self.assertAlmostEqual(initial_margin_usd(4160.,1.,200.),20.8)
        self.assertAlmostEqual(initial_margin_usd(4160.,1.,100.),41.6)
        self.assertAlmostEqual(initial_margin_usd(4160.,1.,1.),4160.)

    def test_default_200_leverage_does_not_force_200x_exposure(self):
        with patch("xaubot.runner.evaluate",return_value=[idea()]):
            report=replay(bars(6))
        self.assertEqual(report["metadata"]["leverage"],200.)
        self.assertEqual(report["metadata"]["strategy_count"],201)
        account=next(x for x in report["strategies"] if x["strategy"]=="GWS_PRIMARY")
        opens=[x for x in report["events"] if x["type"]=="OPEN" and x["strategy"]=="GWS_PRIMARY"]
        self.assertEqual(len(opens),1)
        opened=opens[0]
        self.assertAlmostEqual(opened["initial_margin_usd"],
                               round(opened["notional_usd"]/200.,4),places=4)
        self.assertGreater(opened["initial_margin_usd"],0)
        self.assertLess(opened["initial_margin_usd"],1000)
        self.assertLess(opened["notional_usd"]/1000,200.)
        self.assertGreater(account["open_reserved_initial_margin_usd"],0)
        self.assertEqual(account["margin_rejected"],0)
        self.assertEqual(account["trades"],1)

    def test_margin_rejection_at_one_to_one_but_no_gains_multiplier(self):
        with patch("xaubot.runner.evaluate",return_value=[idea()]):
            report_1x=replay(bars(6),leverage=1)
            report_200x=replay(bars(6),leverage=200)
        low=next(x for x in report_1x["strategies"] if x["strategy"]=="GWS_PRIMARY")
        high=next(x for x in report_200x["strategies"] if x["strategy"]=="GWS_PRIMARY")
        self.assertEqual(low["margin_rejected"],1)
        self.assertEqual(low["trades"],0)
        self.assertEqual(high["margin_rejected"],0)
        self.assertEqual(high["trades"],1)
        rejects=[x for x in report_1x["events"] if x["type"]=="MARGIN_REJECT"]
        self.assertEqual(len(rejects),1)
        self.assertGreater(rejects[0]["requested_margin_usd"],
                           rejects[0]["available_equity_usd"])
        # Same 0.5% stop-risk model, whether exposure is feasible or not.
        self.assertEqual(high["equity"],1000.)
        self.assertEqual(high["pnl"],0.)

    def test_winning_trade_pnl_unaffected_by_higher_available_leverage(self):
        # Inject one strategy candidate, force price to hit TP1 next candle.
        sample=bars(7)
        sample[6]=type(sample[6])(sample[6].time,4164.,4165.,4162.,4164.)
        with patch("xaubot.runner.evaluate",return_value=[idea()]):
            fifty=replay(sample,leverage=50)
            twohundred=replay(sample,leverage=200)
        def account(result):
            return next(x for x in result["strategies"] if x["strategy"]=="GWS_PRIMARY")
        self.assertAlmostEqual(account(fifty)["pnl"],account(twohundred)["pnl"])
        self.assertLess(account(twohundred)["peak_initial_margin_usd"],
                        account(fifty)["peak_initial_margin_usd"])
        self.assertGreater(account(fifty)["pnl"],0)

    def test_invalid_leverage_rejected(self):
        for leverage in (0,-1,math.nan,math.inf,1001):
            with self.subTest(leverage=leverage):
                with self.assertRaisesRegex(ValueError,"leverage"):
                    replay(bars(1),leverage=leverage)

    def test_margin_is_not_deducted_from_equity_on_entry(self):
        with patch("xaubot.runner.evaluate",return_value=[idea()]):
            result=replay(bars(6),leverage=200)
        primary=next(x for x in result["strategies"] if x["strategy"]=="GWS_PRIMARY")
        self.assertEqual(primary["equity"],1000.)
        self.assertGreater(primary["open_reserved_initial_margin_usd"],0)


if __name__=="__main__":
    unittest.main()
