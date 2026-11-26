import json
import os
import time
import wave
from importlib.metadata import version

import numpy as np
from faster_whisper.vad import VadOptions, get_speech_timestamps

import whisper_common

AUDIO = os.environ.get("AUDIO", "audio16k_full.wav")
MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
LOG_PROB_THRESHOLD = float(os.environ.get("WHISPER_LOG_PROB_THRESHOLD", "-0.4"))


def log(msg):
    print(f"[transcribe] {msg}", flush=True)


def read_wav(path):
    with wave.open(str(path), "rb") as fh:
        if fh.getnchannels() != 1 or fh.getframerate() != 16000:
            return None
        if fh.getsampwidth() != 2:
            return None
        raw = fh.readframes(fh.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def write_vad_diagnostic(audio_path):
    try:
        audio = read_wav(audio_path)
    except Exception as exc:
        log(f"vad diagnostic skipped: {exc}")
        return
    if audio is None:
        log("vad diagnostic skipped: expected 16 kHz mono PCM wav")
        return
    try:
        segments = get_speech_timestamps(
            audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=100)
        )
    except Exception as exc:
        log(f"vad diagnostic failed: {exc}")
        return
    data = {
        "note": "diagnostic only; never used to remove ASR output",
        "speech": [
            {
                "start": round(s["start"] / 16000, 3),
                "end": round(s["end"] / 16000, 3),
            }
            for s in segments
        ],
    }
    with open("vad.json", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    log(f"vad diagnostic: {len(data['speech'])} speech regions -> vad.json")


def main():
    whisper_common.seed_everything()
    log(
        f"loading model {whisper_common.MODEL_NAME} "
        f"revision={whisper_common.MODEL_REVISION[:10]} "
        f"seed={whisper_common.SEED}"
    )
    model = whisper_common.load_model(MODEL_DIR)
    log("model ready")

    write_vad_diagnostic(AUDIO)

    settings = whisper_common.decode_settings(LOG_PROB_THRESHOLD)
    manifest = {
        "faster_whisper": version("faster-whisper"),
        "ctranslate2": version("ctranslate2"),
        "numpy": version("numpy"),
        "model": whisper_common.MODEL_NAME,
        "revision": whisper_common.MODEL_REVISION,
        "seed": whisper_common.SEED,
        "device": "cuda",
        "compute_type": "float16",
        "settings": settings,
        "audio": AUDIO,
    }
    with open("run_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)

    log(f"transcribing {AUDIO}")
    t0 = time.time()
    last_report = t0

    def progress(seg, info):
        nonlocal last_report
        now = time.time()
        if now - last_report > 20:
            pct = 100.0 * seg.end / info.duration if info.duration else 0
            log(f"progress {pct:5.1f}% audio={seg.end:7.1f}s elapsed={now - t0:6.1f}s")
            last_report = now

    out_segments, words, info = whisper_common.collect_segments(
        model, AUDIO, LOG_PROB_THRESHOLD, progress
    )
    log(
        f"detected language={info.language} prob={info.language_probability:.2f} "
        f"duration={info.duration:.1f}s"
    )

    with open("whisper_segments.json", "w", encoding="utf-8") as fh:
        json.dump(out_segments, fh, ensure_ascii=False, indent=1)
    with open("whisper_words.json", "w", encoding="utf-8") as fh:
        json.dump(words, fh, ensure_ascii=False, indent=1)

    full_text = " ".join(s["text"] for s in out_segments).strip()
    with open("whisper_transcript.txt", "w", encoding="utf-8") as fh:
        fh.write(full_text + "\n")

    log(
        f"done in {time.time() - t0:.1f}s: {len(out_segments)} segments, "
        f"{len(words)} words, log_prob_threshold={LOG_PROB_THRESHOLD}"
    )


if __name__ == "__main__":
    main()
