import unittest
from app import analytics


class TestAnalytics(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(analytics.clock(0), "00:00:00")
        self.assertEqual(analytics.clock(75), "00:01:15")
        self.assertEqual(analytics.clock(3600), "01:00:00")

    def test_calculate_activity_empty(self):
        self.assertIsNone(analytics.calculate_activity({}, []))
        self.assertIsNone(analytics.calculate_activity({"windows": []}, []))

    def test_calculate_activity_basic(self):
        meta = {
            "duration_seconds": 20.0,
            "windows": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "rel_db": 3.0,
                    "scores": {"LAUGHTER": 0.8},
                    "music": 0.1,
                },
                {
                    "start": 1.0,
                    "end": 2.0,
                    "rel_db": 7.0,
                    "scores": {"SCREAMING": 0.5},
                    "music": 0.6,
                },
            ],
        }
        words = [
            {"start": 0.2, "end": 0.5, "word": "hello"},
            {"start": 1.1, "end": 1.4, "word": "there"},
        ]
        result = analytics.calculate_activity(meta, words, bin_seconds=10)
        self.assertIsNotNone(result)
        self.assertEqual(result["duration"], 20.0)
        self.assertEqual(len(result["bins"]), 2)
        self.assertEqual(result["totals"]["laughter_windows"], 1)
        self.assertEqual(result["totals"]["screaming_windows"], 1)
        self.assertEqual(result["totals"]["music_windows"], 1)
        self.assertEqual(result["totals"]["words"], 2)


if __name__ == "__main__":
    unittest.main()
