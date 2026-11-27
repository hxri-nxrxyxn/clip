import tempfile
import time
import unittest
from pathlib import Path

from app.jobs import Jobs


class TestJobs(unittest.TestCase):
    def test_job_start_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            jobs_mgr = Jobs(runs_dir=runs_dir)

            job = jobs_mgr.start("test_stage", ["python3", "-c", "print('hello from job')"])
            self.assertEqual(job["status"], "running")
            self.assertEqual(job["stage"], "test_stage")

            # wait for process to finish
            time.sleep(0.5)

            status = jobs_mgr.get(job["id"])
            self.assertEqual(status["status"], "succeeded")
            self.assertEqual(status["returncode"], 0)
            self.assertIn("hello from job", status["log_tail"])

    def test_job_prevent_concurrent_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            jobs_mgr = Jobs(runs_dir=runs_dir)

            jobs_mgr.start("test_stage", ["python3", "-c", "import time; time.sleep(1)"])
            with self.assertRaises(RuntimeError):
                jobs_mgr.start("test_stage2", ["echo", "fail"])

            # Clean up
            time.sleep(1.1)


if __name__ == "__main__":
    unittest.main()
