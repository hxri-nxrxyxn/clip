import unittest
from unittest import mock

from app import llm_select


class TestLLMSelect(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(llm_select.clock(0), "00:00:00")
        self.assertEqual(llm_select.clock(75), "00:01:15")
        self.assertEqual(llm_select.clock(3661), "01:01:01")

    def test_extract_json_plain(self):
        raw = '{"start": 10.5, "end": 25.0, "reason": "laugh climax"}'
        res = llm_select._extract_json(raw)
        self.assertEqual(res["start"], 10.5)
        self.assertEqual(res["end"], 25.0)

    def test_extract_json_markdown_fenced(self):
        raw = """Here is the result:
```json
{
  "start": 12.0,
  "end": 24.5,
  "reason": "good joke"
}
```
Done!"""
        res = llm_select._extract_json(raw)
        self.assertEqual(res["start"], 12.0)
        self.assertEqual(res["reason"], "good joke")

    def test_extract_json_embedded(self):
        raw = 'Some text before {"start": 5.0, "end": 15.0, "reason": "test"} and text after'
        res = llm_select._extract_json(raw)
        self.assertEqual(res["start"], 5.0)

    def test_extract_json_invalid(self):
        with self.assertRaises(ValueError):
            llm_select._extract_json("no json here at all")

    def test_heuristic_clip(self):
        candidate = {
            "window_start": 10.0,
            "window_end": 50.0,
            "peak_time": 25.0,
        }
        words = [
            {"start": 14.5, "end": 15.2, "word": "hello"},
            {"start": 24.8, "end": 25.5, "word": "laugh"},
            {"start": 34.2, "end": 35.0, "word": "bye"},
        ]
        clip = llm_select.heuristic_clip(candidate, words)
        self.assertFalse(clip["llm_used"])
        self.assertLessEqual(clip["start"], 25.0)
        self.assertGreaterEqual(clip["end"], 25.0)
        self.assertGreaterEqual(clip["start"], 10.0)
        self.assertLessEqual(clip["end"], 50.0)

    @mock.patch("urllib.request.urlopen")
    def test_server_ready_true(self, mock_urlopen):
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        self.assertTrue(llm_select.server_ready("http://localhost:38405"))

    @mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_server_ready_false(self, mock_urlopen):
        self.assertFalse(llm_select.server_ready("http://localhost:38405"))


if __name__ == "__main__":
    unittest.main()
