import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import vlm


class VlmTests(unittest.TestCase):
    def test_clamp_score(self):
        self.assertEqual(vlm._clamp_score(9), 5)
        self.assertEqual(vlm._clamp_score(-1), 1)
        self.assertEqual(vlm._clamp_score("3"), 3)
        self.assertEqual(vlm._clamp_score("bad"), 1)

    def test_unavailable(self):
        result = vlm.unavailable("offline")
        self.assertFalse(result["vlm_used"])
        self.assertEqual(result["reason"], "offline")


if __name__ == "__main__":
    unittest.main()
