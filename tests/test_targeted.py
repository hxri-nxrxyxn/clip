import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import targeted


class TargetedTests(unittest.TestCase):
    def test_clock_alias(self):
        self.assertEqual(targeted.clock(61), "00:01:01")


if __name__ == "__main__":
    unittest.main()
