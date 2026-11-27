import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import ranking


class RankingTests(unittest.TestCase):
    def test_build_rankings(self):
        selection = {
            "selections": [
                {
                    "candidate_id": 0,
                    "start": 1,
                    "end": 21,
                    "peak_score": 0.9,
                    "types": {"LAUGHTER": 0.9},
                    "reason": "funny",
                },
                {
                    "candidate_id": 1,
                    "start": 30,
                    "end": 40,
                    "peak_score": 0.2,
                    "types": {"SHOUTING": 0.2},
                    "reason": "quiet",
                },
            ]
        }
        visual = {
            "clips": [
                {
                    "candidate_id": 0,
                    "visual_score": 5,
                    "transcript_support": 5,
                    "summary": "funny action",
                    "flags": [],
                    "vlm_used": True,
                },
                {
                    "candidate_id": 1,
                    "visual_score": 1,
                    "transcript_support": 1,
                    "summary": "dark static",
                    "flags": ["dark", "static"],
                    "vlm_used": True,
                },
            ]
        }
        result = ranking.build_rankings(selection, visual)
        self.assertEqual([item["candidate_id"] for item in result], [0, 1])
        self.assertEqual(result[0]["rank"], 1)
        self.assertGreater(result[0]["overall"], result[1]["overall"])

    def test_build_rankings_without_visual(self):
        selection = {
            "selections": [
                {
                    "candidate_id": 0,
                    "start": 1,
                    "end": 10,
                    "peak_score": 0.5,
                    "types": {"LAUGHTER": 0.5},
                }
            ]
        }
        result = ranking.build_rankings(selection)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["visual_used"])


if __name__ == "__main__":
    unittest.main()
