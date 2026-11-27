import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import visual


class VisualTests(unittest.TestCase):
    def test_frame_times_are_inside_clip(self):
        times = visual.frame_times(10.0, 20.0, 6)
        self.assertEqual(len(times), 6)
        self.assertGreater(times[0], 10.0)
        self.assertLess(times[-1], 20.0)
        self.assertEqual(times, sorted(times))

    def test_contact_sheet(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frames = []
            labels = []
            for index in range(6):
                path = root / f"frame_{index}.jpg"
                Image.new("RGB", (160, 90), (index * 20, 40, 80)).save(path)
                frames.append(path)
                labels.append(f"#{index} 00:0{index}")
            out = root / "sheet.jpg"
            self.assertTrue(
                visual.make_contact_sheet(frames, labels, out, columns=3, tile_width=240)
            )
            self.assertTrue(out.is_file())
            with Image.open(out) as image:
                self.assertEqual(image.size, (720, 2 * (135 + 28)))


if __name__ == "__main__":
    unittest.main()
