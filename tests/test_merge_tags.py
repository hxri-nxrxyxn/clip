import sys
import unittest
from pathlib import Path

# Add script dir to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "2-transcribe" / "scripts"))

import merge_tags


class TestMergeTags(unittest.TestCase):
    def test_percentile(self):
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertEqual(merge_tags.percentile(vals, 0), 10.0)
        self.assertEqual(merge_tags.percentile(vals, 100), 50.0)
        self.assertEqual(merge_tags.percentile(vals, 50), 30.0)

    def test_filter_words(self):
        # LOW_CONF_P = 0.15, MIN_WORD_DUR = 0.08, MAX_WORD_DUR = 2.0
        words = [
            {"start": 1.0, "end": 1.5, "probability": 0.8, "word": "valid"},
            # Extremely short duration (0.01s < 0.08) and very low prob (< 0.15) and isolated
            {"start": 10.0, "end": 10.01, "probability": 0.05, "word": "bad_short"},
        ]
        kept = merge_tags.filter_words(words)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["word"], "valid")

    def test_collapse_word_repeats(self):
        words = [
            {"start": 1.0, "end": 1.5, "word": " hello "},
            {"start": 1.6, "end": 2.0, "word": " hello "},
            {"start": 2.1, "end": 2.5, "word": " hello "},
            {"start": 2.6, "end": 3.0, "word": " world "},
        ]
        collapsed = merge_tags.collapse_word_repeats(words)
        hellos = [w for w in collapsed if "hello" in w["word"]]
        self.assertLessEqual(len(hellos), 2)
        self.assertIn("world", collapsed[-1]["word"])

    def test_build_lines(self):
        words = [
            {"start": 0.0, "end": 0.5, "word": "Hello "},
            {"start": 0.6, "end": 1.0, "word": "world"},
            # Big pause (> PAUSE = 0.7s)
            {"start": 2.0, "end": 2.5, "word": "Next "},
            {"start": 2.6, "end": 3.0, "word": "line"},
        ]
        lines = merge_tags.build_lines(words)
        self.assertEqual(len(lines), 2)
        self.assertIn("Hello world", lines[0]["text"])
        self.assertIn("Next line", lines[1]["text"])

    def test_has_speech(self):
        words = [{"start": 10.0, "end": 12.0}]
        self.assertTrue(merge_tags.has_speech(9.0, 11.0, words))
        self.assertFalse(merge_tags.has_speech(0.0, 5.0, words))


if __name__ == "__main__":
    unittest.main()
