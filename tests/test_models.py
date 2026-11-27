import unittest

from app import models


class TestModels(unittest.TestCase):
    def test_job_record_serialization(self):
        rec = models.JobRecord(
            job_id="test1234",
            url="https://youtube.com/watch?v=xyz",
            run_id="run-1",
            status="succeeded",
        )
        d = rec.to_dict()
        self.assertEqual(d["job_id"], "test1234")
        self.assertEqual(d["status"], "succeeded")
        rec2 = models.JobRecord.from_dict(d)
        self.assertEqual(rec2.job_id, "test1234")
        self.assertEqual(rec2.status, "succeeded")

    def test_candidate_clip(self):
        clip = models.CandidateClip(
            id=1,
            window_start=10.0,
            window_end=35.0,
            peak_time=20.0,
            peak_score=0.88,
            types={"LAUGHTER": 0.88},
        )
        d = clip.to_dict()
        self.assertEqual(d["id"], 1)
        self.assertEqual(d["types"]["LAUGHTER"], 0.88)
        self.assertFalse(d["llm_used"])

    def test_activity_summary(self):
        summary = models.ActivitySummary(
            duration=120.0,
            bin_seconds=10,
            bins=[],
            heatmap=[],
            minutes=[],
            totals={"duration": 120.0, "words": 50},
        )
        d = summary.to_dict()
        self.assertEqual(d["duration"], 120.0)
        self.assertEqual(d["totals"]["words"], 50)


if __name__ == "__main__":
    unittest.main()
