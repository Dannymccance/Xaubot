"""DKCapital V2 constraints applied to independent Xaubot paper portfolios."""
import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from xaubot.dk_paper import (
    DKGroup, DKLeg, DKPaperSettings, STOP_ORIGIN,
    _risk_gbp, _units_and_lots, replay_dkcapital,
)
from xaubot.engine import Bar, Candidate

UTC = timezone.utc
TUE = datetime(2026,10,13,10,tzinfo=UTC)
FRI = datetime(2026,10,16,10,tzinfo=UTC)


def settings(**values):
    params = dict(usd_per_gbp=1.25, contract_oz_per_lot=100.,
                  lot_min=.01, lot_step=.01)
    params.update(values)
    return DKPaperSettings(**params)


def bars(start=TUE,n=7):
    return [Bar(start+timedelta(minutes=i),4160,4161,4159,4160.2)
            for i in range(n)]


def idea(stamp,stop=4155.,tp1=4164.,tp2=4166.5,tp3=4172.):
    return Candidate(stamp,"double_top_bottom__c3__t2",
                     "double_top_bottom",1,4160.,4158.,4161.,
                     4157.,4160.,stop,tp1,tp2,tp3,
                     "fallback_3R_hypothesis",50,"synthetic fixture","scalp")


def one_signal(sample,stop=4155.):
    def evaluation(prior):
        return [idea(prior[-1].time+timedelta(minutes=1),stop=stop)]
    with patch("xaubot.dk_paper.evaluate",side_effect=evaluation):
        return replay_dkcapital(sample,settings())


def strategy(result):
    return next(a for a in result["strategies"] if a["strategy"]=="double_top_bottom__c3__t2")


class DKCapitalPaperTests(unittest.TestCase):
    def test_normal_exact_three_leg_allocation(self):
        self.assertEqual(_units_and_lots(1000.,TUE,settings())[0],[.03,.03,.04])
        self.assertEqual(_units_and_lots(500.,TUE,settings())[0],[.01,.02,.02])
        self.assertEqual(_units_and_lots(200.,TUE,settings()),[])
        self.assertEqual(_units_and_lots(100.,TUE,settings()),[])

    def test_friday_uses_iom_and_never_increases_balance_cap(self):
        self.assertEqual(_units_and_lots(1000.,FRI,settings())[0],[.01,.01,.01])
        self.assertEqual(_units_and_lots(300.,FRI,settings())[0],[.01,.01,.01])
        self.assertEqual(_units_and_lots(200.,FRI,settings()),[])

    def test_generated_stop_not_telegram_provider_stop(self):
        result=one_signal(bars())
        self.assertEqual(result["metadata"]["strategy_count"],201)
        self.assertEqual(result["metadata"]["account_currency"],"GBP")
        self.assertEqual(result["metadata"]["leverage"],200)
        self.assertEqual(result["metadata"]["stop_origin"],STOP_ORIGIN)
        self.assertFalse(result["metadata"]["broker_verified"])
        opened=next(e for e in result["events"] if e["type"]=="PAPER_OPEN_THREE_LEGS")
        self.assertEqual([x["label"] for x in opened["legs"]],["TP1","TP2","TP3"])
        self.assertEqual([x["lots"] for x in opened["legs"]],[.03,.03,.04])
        self.assertEqual(opened["stop_origin"],"XAUBOT_GENERATED_HYPOTHESIS")
        self.assertLess(opened["planned_risk_gbp"],75)
        self.assertLess(opened["initial_margin_gbp"],1000)
        self.assertEqual(strategy(result)["trades"],1)

    def test_risk_reduces_lots_without_changing_stop(self):
        result=one_signal(bars(),stop=4140.)
        opened=next(e for e in result["events"] if e["type"]=="PAPER_OPEN_THREE_LEGS")
        self.assertEqual(sum(x["lots"] for x in opened["legs"]),.04)
        self.assertLessEqual(opened["planned_risk_gbp"],75)
        self.assertEqual(opened["stop_usd_per_oz"],4140.)

    def test_too_wide_stop_rejects_all_three(self):
        result=one_signal(bars(),stop=4120.)
        self.assertEqual(strategy(result)["risk_rejected"],1)
        self.assertEqual(strategy(result)["trades"],0)
        self.assertTrue(any(e["type"]=="PAPER_RISK_REJECT" for e in result["events"]))

    def test_margin_fails_closed_independently_from_stop_risk(self):
        # 90 theoretical ounces at minimum 3 × .01 lots, notional
        # requires >GBP1000 at 1:200 despite small stop exposure.
        custom=settings(contract_oz_per_lot=3000.)
        fixture=bars()
        def evaluation(prior):
            return [idea(prior[-1].time+timedelta(minutes=1),stop=4160.2)]
        with patch("xaubot.dk_paper.evaluate",side_effect=evaluation):
            result=replay_dkcapital(fixture,custom)
        self.assertEqual(strategy(result)["trades"],0)
        self.assertEqual(strategy(result)["margin_rejected"],1)

    def test_tp1_moves_remaining_legs_to_paper_be(self):
        fixture=bars(n=8)
        # Next full candle after entry: hits TP1, does not revisit BE.
        fixture[6]=Bar(fixture[6].time,4161,4164.8,4160.6,4164)
        fixture[7]=Bar(fixture[7].time,4164,4164.5,4159,4160)
        result=one_signal(fixture)
        tp1=[e for e in result["events"] if e["type"]=="PAPER_TP1"]
        be=[e for e in result["events"] if e["type"]=="PAPER_BE_AFTER_ASSUMED_TP1"]
        sl=[e for e in result["events"] if e["type"]=="PAPER_SL_OR_BE"]
        self.assertEqual(len(tp1),1)
        self.assertEqual({e["leg"] for e in be},{"TP2","TP3"})
        self.assertEqual(len(sl),2)
        self.assertEqual(strategy(result)["closed"],1)
        self.assertEqual(strategy(result)["open_legs"],0)

    def test_same_minute_stop_and_tp_uses_stop_first(self):
        fixture=bars(n=7)
        fixture[6]=Bar(fixture[6].time,4160,4175,4150,4160)
        result=one_signal(fixture)
        self.assertFalse(any(e["type"]=="PAPER_TP1" for e in result["events"]))
        self.assertEqual(len([e for e in result["events"] if e["type"]=="PAPER_SL_OR_BE"]),3)

    def test_150_gbp_portfolio_cap_sums_multiple_groups(self):
        sample=bars(n=166)
        scheduled={5,55,105,155}
        def evaluation(prior):
            stamp=prior[-1].time+timedelta(minutes=1)
            return [idea(stamp)] if int((stamp-TUE).total_seconds()/60) in scheduled else []
        with patch("xaubot.dk_paper.evaluate",side_effect=evaluation):
            result=replay_dkcapital(sample,settings())
        a=strategy(result)
        self.assertEqual(a["trades"],3)
        self.assertEqual(a["risk_rejected"],1)
        self.assertLessEqual(a["reserved_stop_risk_gbp"],150.)
        self.assertLessEqual(a["peak_reserved_risk_gbp"],150.)
        self.assertEqual(a["open_positions"],3)
        self.assertEqual(a["open_legs"],9)

    def test_market_close_does_not_auto_liquidate(self):
        result=one_signal(bars(n=6))
        self.assertEqual(strategy(result)["open_positions"],1)
        self.assertEqual(strategy(result)["closed"],0)
        self.assertFalse(any(e["type"]=="WEEKEND_CLOSE" for e in result["events"]))

    def test_no_fx_or_invalid_contract_assumptions_block_run(self):
        for bad in (
            dict(usd_per_gbp=0),dict(usd_per_gbp=math.nan),
            dict(contract_oz_per_lot=0),dict(lot_min=0),
            dict(lot_step=0),dict(initial_gbp=2000),
            dict(leverage=0),dict(portfolio_risk_cap_gbp=250),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    settings(**bad)


if __name__=="__main__":
    unittest.main()
