"""Guardrail tests for the restricted Wine CSV ACL repair."""
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / "deploy" / "prepare-wine-bridge-acl.sh"
UNIT = BASE / "deploy" / "xaubot-wine-bridge.service"


class ACLDeployTests(unittest.TestCase):
    def test_acl_repair_is_narrow_and_non_destructive(self):
        s = SCRIPT.read_text()
        self.assertIn("if [[ \"$(id -u)\" -ne 0 ]]", s)
        self.assertIn("xaubot_xauusd_m1_server.csv", s)
        self.assertIn('stat -c %U "$file"', s)
        self.assertIn('setfacl -m u:root:--x "$current"', s)
        self.assertIn('setfacl -m u:root:r-- "$file"', s)
        self.assertIn('setfacl -m d:u:root:r-x "$folder"', s)
        self.assertNotIn("chmod 777", "\n".join(
            line for line in s.splitlines() if not line.strip().startswith("#")))
        self.assertNotIn("systemctl stop", s)
        self.assertNotIn("rm -rf", s)

    def test_bridge_retains_empty_capability_bounds(self):
        unit = UNIT.read_text()
        self.assertIn("\nCapabilityBoundingSet=\n", unit)
        self.assertIn("\nNoNewPrivileges=true\n", unit)
        self.assertIn("\nProtectSystem=strict\n", unit)


if __name__ == "__main__":
    unittest.main()
