import csv
import math
import wave

import numpy as np


def read_wav(path, expected_rate=16000):
    with wave.open(str(path), "rb") as fh:
        if fh.getnchannels() != 1 or fh.getframerate() != expected_rate:
            raise ValueError(
                f"expected {expected_rate} Hz mono wav, got rate={fh.getframerate()} ch={fh.getnchannels()}"
            )
        if fh.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM wav")
        raw = fh.readframes(fh.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def wav_duration(path):
    with wave.open(str(path), "rb") as fh:
        return fh.getnframes() / fh.getframerate()


def rms_db(samples):
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    return 20.0 * math.log10(max(rms, 1e-9))


def load_classes(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(row)
    return rows


def group_indices(rows, trigger_groups, trigger_needles=None):
    if trigger_needles is None:
        trigger_needles = {
            "LAUGHTER": ("laughter",),
            "SCREAMING": ("screaming",),
            "SHOUTING": ("shout",),
        }
    groups = {group: [] for group in trigger_groups}
    for row in rows:
        name = row["display_name"].lower()
        for group in trigger_groups:
            needles = trigger_needles.get(group, ())
            if any(n in name for n in needles):
                groups[group].append(int(row["index"]))
    return groups
