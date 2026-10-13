"""Guardrail checks that forward collection stays opt-in and offline."""
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


class ForwardDeploymentTests(unittest.TestCase):
    def test_forward_is_opt_in_and_networkless(self):
        compose=(BASE/"compose.yaml").read_text(encoding="utf-8")
        block=compose.split("\n  forward:\n",1)[1]
        self.assertIn('profiles: ["forward"]',block)
        self.assertIn("network_mode: none",block)
        self.assertIn("read_only: true",block)
        self.assertIn('cap_drop: ["ALL"]',block)
        self.assertIn("no-new-privileges:true",block)
        self.assertIn('XAUBOT_BROKER_OFFSET_VERIFIED:-0',block)
        self.assertIn("--offset-verified --watch --poll 30",block)
        self.assertIn("--state /app/data/forward_journal.json",block)
        self.assertNotIn("DISCORD_BOT_TOKEN",block)
        self.assertNotIn("MetaTrader5",block)
        self.assertNotIn("order_send",block)

    def test_verification_disabled_by_default(self):
        example=(BASE/".env.example").read_text(encoding="utf-8")
        self.assertIn("XAUBOT_BROKER_OFFSET_VERIFIED=0",example)
        self.assertIn("XAUBOT_BROKER_UTC_OFFSET_MINUTES=120",example)


if __name__ == "__main__":
    unittest.main()
