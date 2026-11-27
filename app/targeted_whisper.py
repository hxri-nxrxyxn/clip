import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, "/app")

import whisper_common

AUDIO = os.environ["AUDIO"]
CANDIDATES = os.environ["CANDIDATES"]
OUT_DIR = Path(os.environ["OUT_DIR"])
MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
LOG_PROB_THRESHOLD = float(os.environ.get("WHISPER_LOG_PROB_THRESHOLD", "-0.4"))


def clock(seconds):
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def read_wav(path):
    with wave.open(str(path), "rb") as fh:
        if fh.getnchannels() != 1 or fh.getframerate() != 16000:
            raise ValueError("expected 16 kHz mono wav")
        if fh.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM wav")
        rate = fh.getframerate()
        raw = fh.readframes(fh.getnframes())
    return rate, np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def main():
    started = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = Path(AUDIO)
    rate, audio = read_wav(audio_path)
    data = json.loads(Path(CANDIDATES).read_text(encoding="utf-8"))
    windows = data["windows"]
    print(f"[targeted-whisper] audio={audio_path} duration={len(audio) / rate:.1f}s", flush=True)
    print(f"[targeted-whisper] windows={len(windows)}", flush=True)

    whisper_common.seed_everything()
    print(f"[targeted-whisper] loading {whisper_common.MODEL_NAME}", flush=True)
    model = whisper_common.load_model(MODEL_DIR)
    settings = whisper_common.decode_settings(LOG_PROB_THRESHOLD)

    segments_out = []
    words_out = []
    seen_words = set()

    for index, window in enumerate(windows, start=1):
        start = max(0.0, float(window["start"]))
        end = min(len(audio) / rate, float(window["end"]))
        first = int(start * rate)
        last = int(end * rate)
        chunk = audio[first:last]
        if len(chunk) < int(0.1 * rate):
            continue
        t0 = time.time()
        segments, _ = model.transcribe(chunk, **settings)
        count = 0
        for segment in segments:
            seg_start = round(segment.start + start, 3)
            seg_end = round(segment.end + start, 3)
            seg_words = []
            for word in segment.words or []:
                text = word.word
                if not text:
                    continue
                item = {
                    "start": round(word.start + start, 3),
                    "end": round(word.end + start, 3),
                    "word": text,
                    "probability": round(float(word.probability), 4),
                }
                key = (item["start"], item["end"], item["word"].strip())
                if key in seen_words:
                    continue
                seen_words.add(key)
                seg_words.append(item)
                words_out.append(item)
            segments_out.append(
                {
                    "start": seg_start,
                    "end": seg_end,
                    "text": segment.text.strip(),
                    "words": seg_words,
                }
            )
            count += 1
        print(
            f"[targeted-whisper] window {index}/{len(windows)} "
            f"{clock(start)}-{clock(end)} -> {count} segments in {time.time() - t0:.1f}s",
            flush=True,
        )

    segments_out.sort(key=lambda item: item["start"])
    words_out.sort(key=lambda item: item["start"])

    with open(OUT_DIR / "targeted_segments.json", "w", encoding="utf-8") as fh:
        json.dump(segments_out, fh, ensure_ascii=False, indent=1)
    with open(OUT_DIR / "targeted_words.json", "w", encoding="utf-8") as fh:
        json.dump(words_out, fh, ensure_ascii=False, indent=1)
    with open(OUT_DIR / "targeted_transcript.txt", "w", encoding="utf-8") as fh:
        for segment in segments_out:
            fh.write(f"[{clock(segment['start'])}] {segment['text']}\n")

    print(
        f"[targeted-whisper] done: {len(segments_out)} segments, "
        f"{len(words_out)} words in {time.time() - started:.1f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
