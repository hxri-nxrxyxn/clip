import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import orchestrator


class TestOrchestrator(unittest.TestCase):
    def test_summary_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp)
            ingest_data = {
                "duration_seconds": 12.5,
                "sample_rate": 16000,
                "source_file": "/path/to/sample.wav",
            }
            with mock.patch("app.storage.ingest_for_run", return_value=ingest_data):
                s = orchestrator.summary("1-ingest", "test-run")
                self.assertEqual(s["duration"], "12.5s")
                self.assertEqual(s["source"], "sample.wav")

    def test_validate_target(self):
        url = "https://youtube.com/watch?v=123"
        self.assertEqual(orchestrator.validate_target(url), url)

        with self.assertRaises(ValueError):
            orchestrator.validate_target("")

        with self.assertRaises(ValueError):
            orchestrator.validate_target("bad\x00character")

    def test_job_label(self):
        job = {"id": "job-1", "video": {"title": "My Awesome Video Title"}}
        self.assertIn("My Awesome Video Title", orchestrator.job_label(job))

        job2 = {"id": "job-2", "url": "https://example.com/stream"}
        self.assertIn("https://example.com/stream", orchestrator.job_label(job2))

        job3 = {"id": "job-3"}
        self.assertEqual(orchestrator.job_label(job3), "job-3")

    def test_jobs_list_includes_current_archive(self):
        with mock.patch.object(
            orchestrator.storage,
            "archived_runs",
            return_value=[{"run_id": "run-1", "video": {"title": "Current"}}],
        ), mock.patch.object(
            orchestrator.storage, "current_run_id", return_value="run-1"
        ), mock.patch.object(
            orchestrator,
            "current_job",
            return_value={"job_id": "job-1", "run_id": "run-1", "status": "succeeded"},
        ):
            jobs = orchestrator.jobs_list()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], "run-1")
        self.assertTrue(jobs[0]["is_current"])

    def test_jobs_list_includes_live_job(self):
        ingest = {"title": "Live", "duration_seconds": 10, "source_file": "/tmp/a.wav"}
        with mock.patch.object(
            orchestrator.storage, "archived_runs", return_value=[]
        ), mock.patch.object(
            orchestrator.storage, "current_run_id", return_value="run-1"
        ), mock.patch.object(
            orchestrator,
            "current_job",
            return_value={"job_id": "job-1", "url": "https://example", "status": "running"},
        ), mock.patch.object(
            orchestrator.storage, "read_current_run_pointer", return_value="run-1"
        ), mock.patch.object(
            orchestrator.storage, "ingest_for_run", return_value=ingest
        ):
            jobs = orchestrator.jobs_list()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], "job-1")
        self.assertTrue(jobs[0]["is_current"])
        self.assertEqual(jobs[0]["video"]["title"], "Live")

    def test_handoff_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "1-ingest" / "output" / "test-run" / "audio" / "audio16k_full.wav"
            src.parent.mkdir(parents=True)
            src.write_text("dummy-audio-content", encoding="utf-8")

            with mock.patch("app.orchestrator.ROOT", root), \
                 mock.patch("app.orchestrator.resolve_run_id", return_value="test-run"):
                res = orchestrator.handoff("1-ingest", "2-transcribe")
                self.assertEqual(res["to"], "2-transcribe")
                self.assertEqual(res["files"], 1)

                dest = root / "2-transcribe" / "input" / "test-run" / "audio16k_full.wav"
                self.assertTrue(dest.is_file())
                self.assertEqual(dest.read_text(encoding="utf-8"), "dummy-audio-content")


if __name__ == "__main__":
    unittest.main()
