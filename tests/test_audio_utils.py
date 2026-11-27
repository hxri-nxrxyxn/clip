import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from app import audio_utils


def create_dummy_wav(path: Path, duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    num_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        # 440 Hz sine wave
        t = np.linspace(0, duration_s, num_frames, endpoint=False)
        data = (np.sin(2 * np.pi * 440 * t) * 16384).astype(np.int16)
        fh.writeframes(data.tobytes())


class TestAudioUtils(unittest.TestCase):
    def test_read_wav_and_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "test.wav"
            create_dummy_wav(wav_path, duration_s=0.5, sample_rate=16000)

            dur = audio_utils.wav_duration(wav_path)
            self.assertAlmostEqual(dur, 0.5, places=2)

            samples = audio_utils.read_wav(wav_path, expected_rate=16000)
            self.assertEqual(len(samples), 8000)
            self.assertEqual(samples.dtype, np.float32)

    def test_read_wav_invalid_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "test.wav"
            create_dummy_wav(wav_path, duration_s=0.5, sample_rate=8000)
            with self.assertRaises(ValueError):
                audio_utils.read_wav(wav_path, expected_rate=16000)

    def test_rms_db(self):
        silence = np.zeros(16000, dtype=np.float32)
        self.assertAlmostEqual(audio_utils.rms_db(silence), -180.0, delta=1.0)

        sine = np.sin(np.linspace(0, 10, 16000)).astype(np.float32)
        db = audio_utils.rms_db(sine)
        self.assertGreater(db, -10.0)

    def test_group_indices(self):
        rows = [
            {"index": "0", "display_name": "Laughter"},
            {"index": "1", "display_name": "Giggle"},
            {"index": "2", "display_name": "Screaming"},
            {"index": "3", "display_name": "Speech"},
        ]
        groups = audio_utils.group_indices(
            rows,
            trigger_groups=["LAUGHTER", "SCREAMING"],
            trigger_needles={
                "LAUGHTER": ("laughter", "giggle"),
                "SCREAMING": ("screaming",),
            },
        )
        self.assertEqual(groups["LAUGHTER"], [0, 1])
        self.assertEqual(groups["SCREAMING"], [2])


if __name__ == "__main__":
    unittest.main()
