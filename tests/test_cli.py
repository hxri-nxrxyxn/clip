import argparse
import unittest
from unittest import mock

from app import cli


class TestCLI(unittest.TestCase):
    def test_parser_run(self):
        parser = cli.build_parser()
        args = parser.parse_args(["run", "pipeline", "--target", "https://example.com/video"])
        self.assertEqual(args.stage, "pipeline")
        self.assertEqual(args.target, "https://example.com/video")
        self.assertEqual(args.func, cli.cmd_run)

    def test_parser_extract(self):
        parser = cli.build_parser()
        args = parser.parse_args(["extract", "job-123", "--rescan", "--limit", "5"])
        self.assertEqual(args.run_id, "job-123")
        self.assertTrue(args.rescan)
        self.assertEqual(args.limit, 5)
        self.assertEqual(args.func, cli.cmd_extract)

    def test_parser_select(self):
        parser = cli.build_parser()
        args = parser.parse_args(["select", "job-123", "--no-llm"])
        self.assertEqual(args.run_id, "job-123")
        self.assertTrue(args.no_llm)
        self.assertEqual(args.func, cli.cmd_select)

    def test_parser_visual(self):
        parser = cli.build_parser()
        args = parser.parse_args(["visual", "job-123", "--no-vlm", "--max-clips", "3"])
        self.assertEqual(args.run_id, "job-123")
        self.assertTrue(args.no_vlm)
        self.assertEqual(args.max_clips, 3)
        self.assertEqual(args.func, cli.cmd_visual)

    def test_parser_handoff(self):
        parser = cli.build_parser()
        args = parser.parse_args(["handoff", "1-ingest", "2-transcribe"])
        self.assertEqual(args.from_stage, "1-ingest")
        self.assertEqual(args.to_stage, "2-transcribe")
        self.assertEqual(args.func, cli.cmd_handoff)

    def test_cmd_handoff_success(self):
        args = argparse.Namespace(from_stage="1-ingest", to_stage="2-transcribe")
        with mock.patch(
            "app.orchestrator.handoff", return_value={"to": "2-transcribe", "files": 1}
        ):
            ret = cli.cmd_handoff(args)
            self.assertEqual(ret, 0)

    def test_cmd_handoff_failure(self):
        args = argparse.Namespace(from_stage="1-ingest", to_stage="invalid")
        with mock.patch("app.orchestrator.handoff", side_effect=ValueError("bad stage")):
            ret = cli.cmd_handoff(args)
            self.assertEqual(ret, 1)


if __name__ == "__main__":
    unittest.main()
