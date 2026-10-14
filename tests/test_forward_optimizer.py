"""Vetted optimizer candidates may join read-only fresh forward journal, never trading."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from test_forward import START, make_bars
from test_optimizer import idea
from xaubot.forward import _lab_shortlist, forward_once, read_journal
from xaubot.variants import registry


class ForwardOptimizerShortlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.csv=root/"xauusd_m1.csv"
        self.state=root/"forward.json"
        self.lab=root/"lab.json"
        self.choice=registry()[0]
        self.lab.write_text(json.dumps({
            "version":1,
            "mode":"ONE_NEW_VARIANT_PER_UTC_DAY_RESEARCH_ONLY",
            "ranking":[{"variant":self.choice.name,
                        "status":"SHORTLIST_FOR_INDEPENDENT_FORWARD_PAPER_TEST"}],
            "paper_forward_shortlist":[self.choice.name],
        }))

    def test_only_vetted_up_to_three_are_selected(self):
        shortlist=_lab_shortlist(self.lab)
        self.assertEqual([v.name for v in shortlist],[self.choice.name])
        data=json.loads(self.lab.read_text())
        data["ranking"][0]["status"]="PROVISIONAL_OFFSET_UNVERIFIED"
        self.lab.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"unqualified"):
            _lab_shortlist(self.lab)

    def test_fresh_baseline_candidate_and_filtered_challenger_are_recorded(self):
        make_bars(self.csv,5)
        base=forward_once(self.csv,self.state,120,
                          offset_verified=True,now=START+timedelta(minutes=5,seconds=10),
                          optimizer_state_path=self.lab)
        self.assertTrue(base["initialized"])
        make_bars(self.csv,10)
        cand=idea(START+timedelta(minutes=10))
        with patch("xaubot.forward.evaluate",return_value=[cand]):
            result=forward_once(
                self.csv,self.state,120,offset_verified=True,
                now=START+timedelta(minutes=10,seconds=30),
                optimizer_state_path=self.lab,
            )
        self.assertEqual(result["new_m5"],1)
        self.assertEqual(result["new_events"],2)
        journal=read_journal(self.state)
        names=[e["candidate"]["strategy"] for e in journal["events"]]
        self.assertIn(cand.strategy,names)
        self.assertIn(self.choice.name,names)
        self.assertEqual(len(set(e["event_id"] for e in journal["events"])),2)
        with patch("xaubot.forward.evaluate") as eval_fn:
            later=forward_once(self.csv,self.state,120,offset_verified=True,
                               now=START+timedelta(minutes=10,seconds=45),
                               optimizer_state_path=self.lab)
        eval_fn.assert_not_called()
        self.assertEqual(later["new_events"],0)


if __name__=="__main__":
    unittest.main()
