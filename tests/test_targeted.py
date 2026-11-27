import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import selection
import targeted_extract


class TargetedTests(unittest.TestCase):
    def test_extract_clock_alias(self):
        self.assertEqual(targeted_extract.clock(61), "00:01:01")

    def test_selection_format_event_line(self):
        line = {"start": 61, "tags": ["LAUGHTER"], "text": "hello"}
        self.assertEqual(selection.format_event_line(line), "[00:01:01] [LAUGHTER] hello")


if __name__ == "__main__":
    unittest.main()
