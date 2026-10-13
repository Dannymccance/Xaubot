"""Static deployment safety regression checks for the Ubuntu bridge unit."""
import unittest
from pathlib import Path


UNIT = Path(__file__).resolve().parents[1] / "deploy" / "xaubot-wine-bridge.service"


class SystemdBridgeTests(unittest.TestCase):
    def test_unit_is_research_only_without_broker_credentials(self):
        raw = UNIT.read_text(encoding="utf-8")
        executable = next(line for line in raw.splitlines() if line.startswith("ExecStart="))
        self.assertIn("-m xaubot.wine_bridge", executable)
        self.assertIn("--watch --poll 30", executable)
        self.assertIn("--symbol XAUUSD", executable)
        self.assertIn("--broker-utc-offset-minutes 120", executable)
        self.assertIn("--out /root/Xaubot/data/xauusd_m1.csv", executable)
        self.assertNotIn("order_send", executable.lower())
        self.assertNotIn("metatrader5.initialize", executable.lower())
        self.assertNotIn("password=", executable.lower())
        self.assertNotIn("discord_bot_token=", raw.lower())
        self.assertIn("NoNewPrivileges=true", raw)
        self.assertIn("ProtectSystem=strict", raw)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", raw)
        self.assertIn("ReadWritePaths=/root/Xaubot/data", raw)

    def test_service_not_part_of_default_docker_stack(self):
        compose = (UNIT.parent.parent / "compose.yaml").read_text(encoding="utf-8")
        self.assertNotIn("xaubot-wine-bridge.service", compose)
        self.assertIn("--csv", compose)


if __name__ == "__main__":
    unittest.main()
