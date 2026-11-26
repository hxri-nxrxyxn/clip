import json
import math
import os
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/work/scripts")

import text_metrics
import whisper_common

THRESHOLD = float(os.environ.get("SWEEP_THRESHOLD", "-0.6"))
RUNS = int(os.environ.get("SWEEP_RUNS", "3"))
AUDIO = os.environ.get("AUDIO", "/work/input/audio16k_full.wav")
MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
CLIPS_SPEC = os.environ.get(
    "CLIPS_SPEC", "/work/scripts/tests/clips.json"
)
RESULTS_JSON = os.environ.get(
    "RESULTS_JSON", "/work/scripts/tests/results.json"
)
AUDIO_TAGS_JSON = os.environ.get(
    "AUDIO_TAGS_JSON", "/work/output/audio_tags.json"
)


def log(msg):
    print(f"[sweep] {msg}", flush=True)


def parse_time(value):
    if isinstance(value, (int, float)):
        return float(value)
    total = 0.0
    for part in str(value).split(":"):
        total = total * 60 + float(part)
    return total


def window_text(words, start, end):
    return " ".join(
        w["word"] for w in words if w["end"] > start and w["start"] < end
    )


def main():
    whisper_common.seed_everything()
    log(
        f"threshold={THRESHOLD} runs={RUNS} seed={whisper_common.SEED} "
        f"revision={whisper_common.MODEL_REVISION[:10]}"
    )
    model = whisper_common.load_model(MODEL_DIR)

    spec = json.load(open(CLIPS_SPEC, encoding="utf-8"))
    positive = spec["positive"]
    negative = spec.get("negative", [])
    pad = float(spec.get("pad_seconds", 1.0))

    windows = []
    if os.path.exists(AUDIO_TAGS_JSON):
        windows = json.load(open(AUDIO_TAGS_JSON, encoding="utf-8"))["windows"]

    results = {
        "threshold": THRESHOLD,
        "runs": [],
        "settings": whisper_common.decode_settings(THRESHOLD),
        "model": whisper_common.MODEL_NAME,
        "revision": whisper_common.MODEL_REVISION,
        "seed": whisper_common.SEED,
        "positive_mode": "full_transcript_window",
    }

    for run in range(1, RUNS + 1):
        t0 = time.time()
        segments, words, info = whisper_common.collect_segments(
            model, AUDIO, THRESHOLD
        )
        full_text = " ".join(s["text"] for s in segments)
        metrics = {
            "h1": text_metrics.low_conf_isolated_count(words),
            "h2": text_metrics.repeated_ngram_count(full_text),
            "h3": text_metrics.words_in_noise_count(words, windows),
        }
        metrics["total"] = metrics["h1"] + metrics["h2"] + metrics["h3"]
        log(f"run {run} full audio: {metrics} ({time.time() - t0:.1f}s)")

        clip_results = {}
        all_positive = True
        for clip in positive:
            start = max(0.0, parse_time(clip["start"]) - pad)
            end = parse_time(clip["end"]) + pad
            text = window_text(words, start, end)
            checks = {p: text_metrics.phrase_in(p, text) for p in clip["phrases"]}
            passed = all(checks.values())
            all_positive = all_positive and passed
            clip_results[clip["id"]] = {
                "pass": passed,
                "checks": checks,
                "window": [round(start, 2), round(end, 2)],
                "text": text,
            }

        negative_results = {}
        negative_pass = True
        for clip in negative:
            segs, _, _ = whisper_common.collect_segments(
                model, clip["path"], THRESHOLD
            )
            text = " ".join(s["text"] for s in segs)
            reps = text_metrics.repeated_ngram_count(text)
            passed = (not text.strip()) or reps == 0
            negative_pass = negative_pass and passed
            negative_results[clip["id"]] = {
                "pass": passed,
                "repeated_ngrams": reps,
                "text": text,
            }

        results["runs"].append(
            {
                "run": run,
                "hallucinations": metrics,
                "clips": clip_results,
                "negative": negative_results,
                "all_positive_pass": all_positive,
                "all_pass": all_positive and negative_pass,
            }
        )
        log(
            f"run {run}: positives={'PASS' if all_positive else 'FAIL'} "
            f"negative={'PASS' if negative_pass else 'FAIL'}"
        )

    positive_counts = {
        clip["id"]: sum(1 for r in results["runs"] if r["clips"][clip["id"]]["pass"])
        for clip in positive
    }
    negative_counts = {
        clip["id"]: sum(1 for r in results["runs"] if r["negative"][clip["id"]]["pass"])
        for clip in negative
    }
    rate_min = max(1, math.ceil(RUNS * 2 / 3))
    summary = {
        "rate_min": rate_min,
        "positive_pass_counts": positive_counts,
        "negative_pass_counts": negative_counts,
        "all_pass_runs": sum(1 for r in results["runs"] if r["all_pass"]),
        "total_hallucinations": sum(
            r["hallucinations"]["total"] for r in results["runs"]
        ),
        "fully_consistent": all(
            count == RUNS for count in positive_counts.values()
        )
        and all(count == RUNS for count in negative_counts.values()),
        "rate_pass": all(count >= rate_min for count in positive_counts.values())
        and all(count >= rate_min for count in negative_counts.values()),
    }
    results["summary"] = summary

    with open(RESULTS_JSON, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    log(f"summary: {summary}")


if __name__ == "__main__":
    main()
