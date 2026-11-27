import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "2-transcribe" / "scripts"))

import run_context


class RunContextTests(unittest.TestCase):
    def test_env_run_id(self):
        with mock.patch.dict(os.environ, {"CLIP_RUN_ID": "job-1"}):
            resolved, input_dir, output_dir = run_context.stage_paths()
        self.assertEqual(resolved, "job-1")
        self.assertEqual(input_dir, run_context.STAGE / "input" / "job-1")
        self.assertEqual(output_dir, run_context.STAGE / "output" / "job-1")


if __name__ == "__main__":
    unittest.main()
