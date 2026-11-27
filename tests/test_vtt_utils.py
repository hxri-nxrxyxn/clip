import unittest

from app import vtt_utils


class TestVttUtils(unittest.TestCase):
    def test_hhmmss(self):
        self.assertEqual(vtt_utils.hhmmss(0), "00:00:00")
        self.assertEqual(vtt_utils.hhmmss(65), "00:01:05")
        self.assertEqual(vtt_utils.hhmmss(3665), "01:01:05")
        self.assertEqual(vtt_utils.hhmmss(3665.8, floor=True), "01:01:05")
        self.assertEqual(vtt_utils.hhmmss(3665.8, floor=False), "01:01:06")

    def test_interval(self):
        self.assertEqual(vtt_utils.interval(10.2, 25.8), "00:00:10-00:00:25")

    def test_vtt_ts(self):
        self.assertEqual(vtt_utils.vtt_ts(0), "00:00:00.000")
        self.assertEqual(vtt_utils.vtt_ts(1.5), "00:00:01.500")
        self.assertEqual(vtt_utils.vtt_ts(3600.123), "01:00:00.123")

    def test_vtt_escape(self):
        self.assertEqual(vtt_utils.vtt_escape("<tag> & 'foo'"), "&lt;tag&gt; &amp; 'foo'")

    def test_wrap_text(self):
        text = "This is a sentence that should wrap properly across lines."
        wrapped = vtt_utils.wrap_text(text, width=20)
        self.assertIn("\n", wrapped)
        for line in wrapped.split("\n"):
            self.assertLessEqual(len(line), 25)

    def test_clean_join(self):
        parts = ["Hello", " ", "world", " ! ", " How", " are", " you ?"]
        self.assertEqual(vtt_utils.clean_join(parts), "Hello world! How are you?")

    def test_normalize_word_and_text(self):
        self.assertEqual(vtt_utils.normalize_word("'Hello,'"), "hello")
        self.assertEqual(vtt_utils.normalize_text("Hello, World!"), "hello world")


if __name__ == "__main__":
    unittest.main()
