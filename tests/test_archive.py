import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import archive


class TestArchive(unittest.TestCase):
    def test_update_job_after_ingest_preserves_video_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hist_dir = root / "app" / "history"
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "run-1"}), encoding="utf-8"
            )
            ingest_dir = root / "1-ingest" / "output" / "run-1"
            (ingest_dir / "audio").mkdir(parents=True)
            (ingest_dir / "ingest.json").write_text(
                json.dumps(
                    {
                        "title": "Test title",
                        "uploader": "Tester",
                        "duration_seconds": 12.5,
                        "source_file": "/tmp/source.wav",
                        "webpage_url": "https://example.com/video",
                    }
                ),
                encoding="utf-8",
            )
            (ingest_dir / "audio" / "audio16k_full.wav").write_text(
                "audio", encoding="utf-8"
            )
            with mock.patch("app.storage.ROOT", root), mock.patch(
                "app.archive.ROOT", root
            ), mock.patch("app.archive.HISTORY_DIR", hist_dir):
                result = archive.update_job_after_stage("run-1", "1-ingest")
            self.assertEqual(result["video"]["title"], "Test title")
            self.assertEqual(result["video"]["uploader"], "Tester")

    def test_start_targeted_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            run_json = run_dir / "run.json"
            run_json.write_text(json.dumps({"run_id": "run-1"}), encoding="utf-8")

            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                res = archive.start_targeted_run("run-1")
                self.assertEqual(res["targeted"]["status"], "running")
                self.assertEqual(res["targeted"]["mode"], "yamnet_qwen")

    def test_mark_targeted_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            run_json = run_dir / "run.json"
            run_json.write_text(json.dumps({"run_id": "run-1"}), encoding="utf-8")

            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                res = archive.mark_targeted_failed("run-1", "OOM error")
                self.assertEqual(res["targeted"]["status"], "failed")
                self.assertEqual(res["targeted"]["error"], "OOM error")

    def test_update_targeted_after_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            run_json = run_dir / "run.json"
            run_json.write_text(json.dumps({"run_id": "run-1"}), encoding="utf-8")

            out_dir = Path(tmp) / "mock_output"
            out_dir.mkdir()
            (out_dir / "candidates.json").write_text('{"candidates": [1, 2]}', encoding="utf-8")
            (out_dir / "selection.json").write_text(
                '{"selections": [{"start": 1, "end": 2}]}', encoding="utf-8"
            )
            (out_dir / "timings.json").write_text('{"total_seconds": 1.5}', encoding="utf-8")

            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                res = archive.update_targeted_after_run("run-1", out_dir=out_dir)
                self.assertEqual(res["targeted"]["status"], "succeeded")
                summary = res["targeted"]["summary"]
                self.assertEqual(summary["candidates"], 2)
                self.assertEqual(summary["selections"], 1)


if __name__ == "__main__":
    unittest.main()
