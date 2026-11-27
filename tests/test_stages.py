import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import stages


class StageTests(unittest.TestCase):
    def test_format_path_uses_run_id(self):
        with mock.patch.object(stages, "resolve_run_id", return_value="job-1"):
            self.assertEqual(
                stages.format_path("1-ingest/output/{run_id}/ingest.json"),
                "1-ingest/output/job-1/ingest.json",
            )

    def test_format_path_legacy_without_run_id(self):
        with mock.patch.object(stages, "resolve_run_id", return_value=None):
            self.assertEqual(
                stages.format_path("1-ingest/output/{run_id}/ingest.json"),
                "1-ingest/output/ingest.json",
            )

    def test_outputs_excludes_targeted_subdirectory(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = root / "2-transcribe" / "output" / "job-1"
            (job / "targeted").mkdir(parents=True)
            (job / "transcript.txt").write_text("hello", encoding="utf-8")
            (job / "targeted" / "selection.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(stages, "ROOT", root):
                items = stages.outputs("2-transcribe", run_id="job-1")
        names = {item["name"] for item in items}
        self.assertEqual(names, {"transcript.txt"})


if __name__ == "__main__":
    unittest.main()
