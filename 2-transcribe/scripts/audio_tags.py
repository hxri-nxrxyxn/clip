import json
import sys
from pathlib import Path

import numpy as np
from ai_edge_litert.interpreter import Interpreter

SCRIPT_DIR = Path(__file__).resolve().parent
from run_context import ROOT, STAGE, stage_paths

_RUN_ID, _IN, OUT = stage_paths()

sys.path.insert(0, str(ROOT / "app"))
import audio_utils
import config

AUDIO = OUT / "audio" / "audio16k.wav"
MODEL = config.path("yamnet", "model") or STAGE / "services" / "yamnet" / "yamnet.tflite"
CLASS_MAP = config.path("yamnet", "class_map") or STAGE / "services" / "yamnet" / "yamnet_class_map.csv"
SAMPLE_RATE = int(config.get("yamnet", "sample_rate", 16000))
WIN = int(config.get("yamnet", "window", 16000))
HOP = int(config.get("yamnet", "hop", 8000))
YAMNET_SAMPLES = int(config.get("yamnet", "yamnet_samples", 15600))
TAG_MEMBERSHIP = float(config.get("yamnet", "tag_membership", 0.20))
PEAK_FLOOR = float(config.get("yamnet", "peak_floor", 0.35))
LOUD_DB = float(config.get("yamnet", "loud_db", 6.0))
MUSIC_THRESHOLD = float(config.get("yamnet", "music_threshold", 0.5))
MUSIC_INDEX = int(config.get("yamnet", "music_index", 132))
TRIGGER_GROUPS = tuple(
    config.get("yamnet", "trigger_groups", ["LAUGHTER", "SCREAMING", "SHOUTING"])
)
TRIGGER_NEEDLES = {
    "LAUGHTER": ("laughter",),
    "SCREAMING": ("screaming",),
    "SHOUTING": ("shout",),
}

read_wav = lambda path: audio_utils.read_wav(path, SAMPLE_RATE)
load_classes = audio_utils.load_classes
rms_db = audio_utils.rms_db


def group_indices(rows):
    return audio_utils.group_indices(rows, TRIGGER_GROUPS, TRIGGER_NEEDLES)


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
                "music_threshold": MUSIC_THRESHOLD,
                "music_index": MUSIC_INDEX,
                "trigger_groups": list(TRIGGER_GROUPS),
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
