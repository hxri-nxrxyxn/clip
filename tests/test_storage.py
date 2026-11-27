import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import storage


class StorageTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(storage.slug("Video ID / one"), "Video-ID-one")
        self.assertEqual(storage.slug(""), "run")

    def test_run_id_for_ingest(self):
        created = datetime(2026, 11, 27, 8, 0, 0, tzinfo=UTC)
        self.assertEqual(
            storage.run_id_for_ingest(
                {"created_at": created.isoformat()},
                {"video_id": "Q9BVIwyUr9k"},
            ),
            "Q9BVIwyUr9k-20261127-080000",
        )

    def test_stage_paths(self):
        self.assertEqual(
            storage.stage_output_dir("2-transcribe", "job-1"),
            storage.ROOT / "2-transcribe" / "output" / "job-1",
        )
        self.assertEqual(
            storage.stage_input_dir("2-transcribe", "job-1"),
            storage.ROOT / "2-transcribe" / "input" / "job-1",
        )

    def test_reconcile_current_job(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "current_job.json"
            marker.write_text(json.dumps({"job_id": "x", "status": "running"}), encoding="utf-8")
            with mock.patch.object(storage, "CURRENT_JOB_PATH", marker):
                record = storage.reconcile_current_job()
            self.assertEqual(record["status"], "failed")

    def test_transcribe_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "whisper_words.json").write_text("[]", encoding="utf-8")
            (path / "whisper_segments.json").write_text("[]", encoding="utf-8")
            (path / "audio_tags.json").write_text('{"windows": [1, 2]}', encoding="utf-8")
            (path / "run_manifest.json").write_text('{"model": "test"}', encoding="utf-8")
            summary = storage.transcribe_summary_from_path(path)
        self.assertEqual(summary["words"], 0)
        self.assertEqual(summary["tags"], 2)
        self.assertEqual(summary["model"], "test")


if __name__ == "__main__":
    unittest.main()
