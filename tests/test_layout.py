import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import layout


class LayoutTests(unittest.TestCase):
    def test_move_path_preserves_gitkeep(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / ".gitkeep").write_text("", encoding="utf-8")
            (source / "file.txt").write_text("data", encoding="utf-8")
            destination = root / "destination"
            layout.move_path(source, destination)
            self.assertTrue((source / ".gitkeep").is_file())
            self.assertTrue((destination / "file.txt").is_file())
            self.assertFalse((destination / ".gitkeep").exists())

    def test_path_size(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("1234", encoding="utf-8")
            self.assertEqual(layout.path_size(root), 4)

    def test_cleanup_paths_cover_all_stages(self):
        paths = layout.cleanup_paths("job-1")
        names = {str(path) for path in paths}
        for stage_id in layout.pipeline.STAGE_IDS:
            self.assertIn(str(layout.pipeline.stage_input_dir(stage_id, "job-1")), names)
            self.assertIn(str(layout.pipeline.stage_output_dir(stage_id, "job-1")), names)


if __name__ == "__main__":
    unittest.main()
