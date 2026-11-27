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

    def test_split_legacy_targeted(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            targeted = run_dir / "targeted"
            targeted.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "targeted": {
                            "status": "succeeded",
                            "mode": "yamnet_qwen",
                            "path": "targeted",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (targeted / "selection.json").write_text(
                '{"llm_ready": true, "selections": [{"start": 1, "end": 2}]}',
                encoding="utf-8",
            )
            (targeted / "timings.json").write_text(
                '{"candidates": 1, "llm_seconds": 1.0, "total_seconds": 1.5}',
                encoding="utf-8",
            )
            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                self.assertTrue(archive.split_legacy_targeted("run-1"))
            record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(record["selection"]["mode"], "qwen")
            self.assertTrue((run_dir / "selection" / "selection.json").is_file())

    def test_visual_run_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "run-1"}), encoding="utf-8"
            )
            out_dir = Path(tmp) / "mock_visual"
            (out_dir / "contact_sheets").mkdir(parents=True)
            (out_dir / "contact_sheets" / "clip_00.jpg").write_text(
                "image", encoding="utf-8"
            )
            (out_dir / "visual_analysis.json").write_text(
                json.dumps(
                    {
                        "vlm_ready": True,
                        "clips": [
                            {
                                "candidate_id": 0,
                                "start": 1,
                                "end": 2,
                                "contact_sheet": "contact_sheets/clip_00.jpg",
                                "visual_score": 4,
                                "vlm_used": True,
                                "summary": "test",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (out_dir / "visual_timings.json").write_text("{}", encoding="utf-8")
            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                running = archive.start_visual_run("run-1")
                self.assertEqual(running["visual"]["status"], "running")
                result = archive.update_visual_after_run("run-1", out_dir=out_dir)
                detail = archive.visual_detail("run-1")
            self.assertEqual(result["visual"]["status"], "succeeded")
            self.assertEqual(detail["summary"]["clips"], 1)
            self.assertEqual(detail["clips"][0]["visual_score"], 4)

    def test_start_targeted_extract_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "run-1"}), encoding="utf-8"
            )

            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                res = archive.start_targeted_extract_run("run-1")
            self.assertEqual(res["targeted"]["status"], "running")
            self.assertEqual(res["targeted"]["mode"], "yamnet_targeted_whisper")

    def test_mark_targeted_extract_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "run-1"}), encoding="utf-8"
            )

            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                res = archive.mark_targeted_extract_failed("run-1", "OOM error")
            self.assertEqual(res["targeted"]["status"], "failed")
            self.assertEqual(res["targeted"]["error"], "OOM error")

    def test_update_targeted_extract_after_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "run-1"}), encoding="utf-8"
            )
            out_dir = Path(tmp) / "mock_output"
            out_dir.mkdir()
            (out_dir / "candidates.json").write_text(
                '{"candidates": [1, 2]}', encoding="utf-8"
            )
            (out_dir / "targeted_segments.json").write_text("[]", encoding="utf-8")
            (out_dir / "targeted_words.json").write_text("[]", encoding="utf-8")
            (out_dir / "timings.json").write_text(
                '{"targeted_whisper_seconds": 2.5, "total_seconds": 3.5}',
                encoding="utf-8",
            )

            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                res = archive.update_targeted_extract_after_run("run-1", out_dir=out_dir)
            self.assertEqual(res["targeted"]["status"], "succeeded")
            self.assertEqual(res["targeted"]["summary"]["candidates"], 2)

    def test_start_selection_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "run-1"}), encoding="utf-8"
            )

            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                res = archive.start_selection_run("run-1")
            self.assertEqual(res["selection"]["status"], "running")
            self.assertEqual(res["selection"]["mode"], "qwen")

    def test_update_selection_after_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp)
            run_dir = hist_dir / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "run-1"}), encoding="utf-8"
            )
            out_dir = Path(tmp) / "mock_selection"
            out_dir.mkdir()
            (out_dir / "selection.json").write_text(
                '{"llm_ready": true, "selections": [{"start": 1, "end": 2}]}',
                encoding="utf-8",
            )
            (out_dir / "timings.json").write_text(
                '{"candidates": 1, "llm_seconds": 1.0, "total_seconds": 1.5}',
                encoding="utf-8",
            )

            with mock.patch("app.archive.HISTORY_DIR", hist_dir):
                res = archive.update_selection_after_run("run-1", out_dir=out_dir)
            self.assertEqual(res["selection"]["status"], "succeeded")
            self.assertEqual(res["selection"]["summary"]["selections"], 1)


if __name__ == "__main__":
    unittest.main()
