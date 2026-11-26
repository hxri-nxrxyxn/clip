import csv
import json
import math
import wave
from pathlib import Path

import numpy as np
from ai_edge_litert.interpreter import Interpreter

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE = SCRIPT_DIR.parent
OUT = STAGE / "output"

AUDIO = OUT / "audio" / "audio16k.wav"
MODEL = STAGE / "services" / "yamnet" / "yamnet.tflite"
CLASS_MAP = STAGE / "services" / "yamnet" / "yamnet_class_map.csv"
SAMPLE_RATE = 16000
WIN = 16000
HOP = 8000
YAMNET_SAMPLES = 15600
TAG_MEMBERSHIP = 0.20
PEAK_FLOOR = 0.35
LOUD_DB = 6.0
MUSIC_INDEX = 132

GROUPS = {
    "LAUGHTER": ("laughter",),
    "SCREAMING": ("screaming",),
    "SHOUTING": ("shout",),
}


def read_wav(path):
    with wave.open(str(path), "rb") as fh:
        if fh.getnchannels() != 1 or fh.getframerate() != SAMPLE_RATE:
            raise ValueError("expected 16 kHz mono wav")
        raw = fh.readframes(fh.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def load_classes(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(row)
    return rows


def group_indices(rows):
    out = {}
    for group, needles in GROUPS.items():
        idx = []
        for row in rows:
            name = row["display_name"].lower()
            if any(n in name for n in needles):
                idx.append(int(row["index"]))
        out[group] = idx
    return out


def rms_db(samples):
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    return 20.0 * math.log10(max(rms, 1e-9))


def main():
    audio = read_wav(AUDIO)
    duration = len(audio) / SAMPLE_RATE
    rows = load_classes(CLASS_MAP)
    groups = group_indices(rows)
    print(f"[yamnet] class indices: {groups}", flush=True)

    interp = Interpreter(model_path=str(MODEL))
    interp.allocate_tensors()
    inputs = interp.get_input_details()
    outputs = interp.get_output_details()
    in_idx = inputs[0]["index"]
    out_idx = next(
        d["index"] for d in outputs if d["shape"][-1] == len(rows)
    )
    print(f"[yamnet] input {inputs[0]['shape']} output {outputs[0]['shape']}", flush=True)

    windows = []
    for start in range(0, len(audio), HOP):
        chunk = audio[start : start + WIN]
        if len(chunk) < WIN:
            chunk = np.pad(chunk, (0, WIN - len(chunk)))
        yam = chunk[:YAMNET_SAMPLES]
        interp.set_tensor(in_idx, yam.reshape(-1).astype(np.float32))
        interp.invoke()
        scores = interp.get_tensor(out_idx)[0]

        tags = {}
        for group, idx in groups.items():
            tags[group] = round(float(np.max(scores[idx])), 4) if idx else 0.0

        windows.append(
            {
                "start": round(start / SAMPLE_RATE, 3),
                "end": round(min((start + WIN) / SAMPLE_RATE, duration), 3),
                "rms_db": round(rms_db(chunk), 2),
                "scores": tags,
                "music": round(float(scores[MUSIC_INDEX]), 4),
            }
        )

    voiced = [w["rms_db"] for w in windows if w["rms_db"] > -55.0]
    baseline = float(np.median(voiced)) if voiced else -60.0
    for w in windows:
        w["rel_db"] = round(w["rms_db"] - baseline, 2)
    with open(OUT / "audio_tags.json", "w", encoding="utf-8") as fh:
        json.dump(
            {
                "sample_rate": SAMPLE_RATE,
                "duration_seconds": round(duration, 3),
                "window_seconds": WIN / SAMPLE_RATE,
                "hop_seconds": HOP / SAMPLE_RATE,
                "baseline_db": round(baseline, 2),
                "tag_membership": TAG_MEMBERSHIP,
                "peak_floor": PEAK_FLOOR,
                "loud_db_threshold": LOUD_DB,
                "music_index": MUSIC_INDEX,
                "windows": windows,
            },
            fh,
            indent=1,
        )
    fired = sum(
        1
        for w in windows
        if any(v >= TAG_MEMBERSHIP for v in w["scores"].values())
    )
    loud = sum(1 for w in windows if w["rel_db"] >= LOUD_DB)
    print(
        f"[yamnet] {len(windows)} windows, baseline {baseline:.1f} dBFS, "
        f"{fired} tagged, {loud} loud",
        flush=True,
    )


if __name__ == "__main__":
    main()
