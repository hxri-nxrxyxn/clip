import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
from ai_edge_litert.interpreter import Interpreter

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import audio_utils
import llm_select
import pipeline

ROOT = pipeline.ROOT
YAMNET_MODEL = config.path("yamnet", "model")
YAMNET_CLASS_MAP = config.path("yamnet", "class_map")
COMPOSE = ROOT / "2-transcribe" / "services" / "whisper" / "docker-compose.yml"

SAMPLE_RATE = int(config.get("yamnet", "sample_rate", 16000))
WIN = int(config.get("yamnet", "window", 16000))
HOP = int(config.get("yamnet", "hop", 8000))
YAMNET_SAMPLES = int(config.get("yamnet", "yamnet_samples", 15600))
MUSIC_INDEX = int(config.get("yamnet", "music_index", 132))
TRIGGER_GROUPS = tuple(config.get("yamnet", "trigger_groups", ["LAUGHTER", "SCREAMING", "SHOUTING"]))
TAG_MEMBERSHIP = float(config.get("yamnet", "tag_membership", 0.20))
PEAK_FLOOR = float(config.get("yamnet", "peak_floor", 0.35))
LOUD_DB = float(config.get("yamnet", "loud_db", 6.0))
MUSIC_THRESHOLD = float(config.get("targeted", "music_threshold", 0.5))
QUIET_REL_DB = float(config.get("targeted", "quiet_rel_db", -6.0))
SNAP_MAX_SHIFT = float(config.get("targeted", "snap_max_shift", 5.0))
TRIGGER_NEEDLES = {
    "LAUGHTER": ("laughter",),
    "SCREAMING": ("screaming",),
    "SHOUTING": ("shout",),
}

read_wav = audio_utils.read_wav
wav_duration = audio_utils.wav_duration
load_classes = lambda: audio_utils.load_classes(YAMNET_CLASS_MAP)
group_indices = lambda rows: audio_utils.group_indices(rows, TRIGGER_GROUPS, TRIGGER_NEEDLES)
rms_db = audio_utils.rms_db


def run_yamnet(audio_path, out_path):
    started = time.time()
    audio = read_wav(audio_path)
    duration = len(audio) / SAMPLE_RATE
    rows = load_classes()
    groups = group_indices(rows)
    print(f"[prototype] YAMNet groups: {groups}", flush=True)

    interpreter = Interpreter(model_path=str(YAMNET_MODEL))
    interpreter.allocate_tensors()
    inputs = interpreter.get_input_details()
    outputs = interpreter.get_output_details()
    in_idx = inputs[0]["index"]
    out_idx = next(d for d in outputs if d["shape"][-1] == len(rows))

    windows = []
    for start in range(0, len(audio), HOP):
        chunk = audio[start : start + WIN]
        if len(chunk) < WIN:
            chunk = np.pad(chunk, (0, WIN - len(chunk)))
        yam = chunk[:YAMNET_SAMPLES]
        interpreter.set_tensor(in_idx, yam.reshape(-1).astype(np.float32))
        interpreter.invoke()
        scores = interpreter.get_tensor(out_idx)[0]
        tags = {}
        for group, indices in groups.items():
            tags[group] = round(float(np.max(scores[indices])), 4) if indices else 0.0
        windows.append(
            {
                "start": round(start / SAMPLE_RATE, 3),
                "end": round(min((start + WIN) / SAMPLE_RATE, duration), 3),
                "rms_db": round(rms_db(chunk), 2),
                "scores": tags,
                "music": round(float(scores[MUSIC_INDEX]), 4),
            }
        )

    voiced = [item["rms_db"] for item in windows if item["rms_db"] > -55.0]
    baseline = float(np.median(voiced)) if voiced else -60.0
    for item in windows:
        item["rel_db"] = round(item["rms_db"] - baseline, 2)

    meta = {
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
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    print(
        f"[prototype] YAMNet done: {len(windows)} windows in {time.time() - started:.1f}s",
        flush=True,
    )
    return meta


def merge_quiet(windows, threshold=QUIET_REL_DB):
    intervals = []
    for item in windows:
        if item["rel_db"] > threshold:
            continue
        start, end = float(item["start"]), float(item["end"])
        if intervals and start - intervals[-1][1] <= 0.5:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    return intervals


def load_vad(path):
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [(float(item["start"]), float(item["end"])) for item in data.get("speech", [])]


def snap_start(value, speech, quiet, max_shift=SNAP_MAX_SHIFT):
    for start, end in speech:
        if start <= value <= end:
            if value - start <= max_shift:
                return start
            break
    options = [start for start, _ in quiet if abs(start - value) <= max_shift]
    return min(options, key=lambda item: abs(item - value)) if options else value


def snap_end(value, speech, quiet, max_shift=SNAP_MAX_SHIFT):
    for start, end in speech:
        if start <= value <= end:
            if end - value <= max_shift:
                return end
            break
    options = [end for _, end in quiet if abs(end - value) <= max_shift]
    return min(options, key=lambda item: abs(item - value)) if options else value


def build_candidates(meta, pre, post, merge_gap, limit, vad_path):
    windows = meta["windows"]
    membership = TAG_MEMBERSHIP
    peak_floor = PEAK_FLOOR
    duration = float(meta.get("duration_seconds") or max(w["end"] for w in windows))
    speech = load_vad(vad_path)
    quiet = merge_quiet(windows, QUIET_REL_DB)

    active = []
    for item in windows:
        scores = item.get("scores") or {}
        matched = {
            group: float(scores.get(group, 0.0))
            for group in TRIGGER_GROUPS
            if float(scores.get(group, 0.0)) >= membership
        }
        if matched:
            active.append((item, matched))

    blocks = []
    for item, matched in active:
        if blocks and item["start"] - blocks[-1]["end"] <= merge_gap:
            block = blocks[-1]
            block["end"] = max(block["end"], item["end"])
            block["windows"].append((item, matched))
        else:
            blocks.append(
                {
                    "start": item["start"],
                    "end": item["end"],
                    "windows": [(item, matched)],
                }
            )

    candidates = []
    for block in blocks:
        peak_item, peak_matched = max(
            block["windows"],
            key=lambda pair: max(pair[1].values(), default=0.0),
        )
        peak_score = max(peak_matched.values(), default=0.0)
        if peak_score < peak_floor:
            continue
        types = {}
        for item, matched in block["windows"]:
            for group, score in matched.items():
                types[group] = max(types.get(group, 0.0), round(score, 4))
        expanded_start = max(0.0, float(block["start"]) - pre)
        expanded_end = min(duration, float(block["end"]) + post)
        window_start = snap_start(expanded_start, speech, quiet, SNAP_MAX_SHIFT)
        window_end = snap_end(expanded_end, speech, quiet, SNAP_MAX_SHIFT)
        if window_end <= window_start:
            window_start, window_end = expanded_start, expanded_end
        candidates.append(
            {
                "start": round(float(block["start"]), 3),
                "end": round(float(block["end"]), 3),
                "peak_time": round(float(peak_item["start"]), 3),
                "peak_score": round(float(peak_score), 4),
                "types": types,
                "window_start": round(float(window_start), 3),
                "window_end": round(float(window_end), 3),
            }
        )

    if limit > 0 and len(candidates) > limit:
        candidates = sorted(candidates, key=lambda item: item["peak_score"], reverse=True)[
            :limit
        ]
    candidates.sort(key=lambda item: item["start"])

    merged = []
    for candidate in candidates:
        if merged and candidate["window_start"] <= merged[-1]["window_end"]:
            current = merged[-1]
            current["window_start"] = min(
                current["window_start"], candidate["window_start"]
            )
            current["window_end"] = max(current["window_end"], candidate["window_end"])
            current["start"] = min(current["start"], candidate["start"])
            current["end"] = max(current["end"], candidate["end"])
            if candidate["peak_score"] > current["peak_score"]:
                current["peak_score"] = candidate["peak_score"]
                current["peak_time"] = candidate["peak_time"]
            for group, score in candidate["types"].items():
                current["types"][group] = max(current["types"].get(group, 0.0), score)
        else:
            merged.append(dict(candidate))

    for index, candidate in enumerate(merged):
        candidate["id"] = index

    payload = {
        "run_id": None,
        "duration": duration,
        "pre": pre,
        "post": post,
        "merge_gap": merge_gap,
        "candidates": merged,
        "windows": [
            {"start": item["window_start"], "end": item["window_end"]}
            for item in merged
        ],
    }
    return payload


def run_targeted_whisper(audio_path, out_dir, candidates_path):
    started = time.time()
    audio_rel = audio_path.relative_to(ROOT).as_posix()
    out_rel = out_dir.relative_to(ROOT).as_posix()
    candidates_rel = candidates_path.relative_to(ROOT).as_posix()
    command = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE),
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "-v",
        f"{ROOT}:/repo",
        "-w",
        f"/repo/{out_rel}",
        "-e",
        f"AUDIO=/repo/{audio_rel}",
        "-e",
        f"CANDIDATES=/repo/{candidates_rel}",
        "-e",
        f"OUT_DIR=/repo/{out_rel}",
        "-e",
        "MODEL_DIR=/models",
        "-e",
        f"WHISPER_MODEL={config.get('whisper', 'model', 'large-v3-turbo')}",
        "-e",
        f"WHISPER_MODEL_REVISION={config.get('whisper', 'revision', '')}",
        "-e",
        f"WHISPER_LOG_PROB_THRESHOLD={config.get('whisper', 'log_prob_threshold', -0.4)}",
        "-e",
        f"WHISPER_SEED={config.get('whisper', 'seed', 1234)}",
        "-e",
        f"WHISPER_LOCAL_FILES_ONLY={'1' if config.get('whisper', 'local_files_only', False) else '0'}",
        "whisper",
        "python3",
        "/repo/app/targeted_whisper.py",
    ]
    print("[prototype] running targeted Whisper…", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    return time.time() - started


def tags_for_interval(start, end, windows, membership, loud_threshold, music_threshold):
    overlapping = [
        item for item in windows if item["end"] > start and item["start"] < end
    ]
    tags = []
    for group in TRIGGER_GROUPS:
        score = max(
            (float((item.get("scores") or {}).get(group, 0.0)) for item in overlapping),
            default=0.0,
        )
        if score >= membership:
            tags.append(group)
    if any(float(item.get("rel_db", -999)) >= loud_threshold for item in overlapping):
        tags.append("LOUD")
    if any(float(item.get("music", 0.0)) >= music_threshold for item in overlapping):
        tags.append("MUSIC")
    return tags


def build_event_lines(segments, meta):
    membership = TAG_MEMBERSHIP
    loud_threshold = LOUD_DB
    music_threshold = MUSIC_THRESHOLD
    windows = meta["windows"]
    lines = []
    for segment in segments:
        text = segment.get("text", "").strip()
        if not text:
            continue
        lines.append(
            {
                "start": segment["start"],
                "end": segment["end"],
                "text": text,
                "tags": tags_for_interval(
                    float(segment["start"]),
                    float(segment["end"]),
                    windows,
                    membership,
                    loud_threshold,
                    music_threshold,
                ),
            }
        )
    return lines


def format_event_line(line):
    tags = "".join(f"[{tag}]" for tag in line["tags"])
    prefix = f"[{clock(line['start'])}]"
    return f"{prefix} {tags} {line['text']}".replace("]  ", "] ")


def select_candidates(payload, lines, words, args, api_key, base_url):
    llm_ready = False
    if not args.no_llm:
        llm_ready = llm_select.server_ready(base_url, api_key)
        print(
            f"[prototype] Qwen {'available' if llm_ready else 'unavailable; using fallback'}",
            flush=True,
        )
    selections = []
    llm_seconds = 0.0
    for candidate in payload["candidates"]:
        window_start = float(candidate["window_start"])
        window_end = float(candidate["window_end"])
        candidate_lines = [
            line
            for line in lines
            if line["end"] > window_start and line["start"] < window_end
        ]
        candidate_words = [
            word
            for word in words
            if word["end"] > window_start and word["start"] < window_end
        ]
        started = time.time()
        used_llm = False
        if llm_ready and candidate_lines:
            try:
                result = llm_select.select_clip(
                    candidate,
                    candidate_lines,
                    candidate_words,
                    base_url=base_url,
                    model=args.llm_model,
                    api_key=api_key,
                    timeout=args.llm_timeout,
                )
                used_llm = result["llm_used"]
                reason = result["reason"]
                start = result["start"]
                end = result["end"]
            except Exception as exc:
                print(f"[prototype] LLM failed for candidate {candidate['id']}: {exc}", flush=True)
                result = llm_select.heuristic_clip(candidate, candidate_words)
                used_llm = False
                reason = result["reason"]
                start = result["start"]
                end = result["end"]
        else:
            result = llm_select.heuristic_clip(candidate, candidate_words)
            reason = result["reason"]
            start = result["start"]
            end = result["end"]
        llm_seconds += time.time() - started
        selections.append(
            {
                "candidate_id": candidate["id"],
                "start": start,
                "end": end,
                "peak_time": candidate["peak_time"],
                "peak_score": candidate["peak_score"],
                "types": candidate["types"],
                "reason": reason,
                "llm_used": used_llm,
                "transcript": "\n".join(
                    format_event_line(line) for line in candidate_lines
                ),
            }
        )
    return selections, llm_ready, llm_seconds


def resolve_archive(run_id):
    if run_id:
        path = pipeline.HISTORY_DIR / run_id
        if not (path / "run.json").is_file():
            raise SystemExit(f"history entry not found: {run_id}")
        return run_id, path
    jobs = pipeline.jobs()
    candidates = [
        job
        for job in jobs
        if job.get("path") and (Path(job["path"]) / "audio16k_full.wav").is_file()
    ]
    if not candidates:
        raise SystemExit("no archived job with audio found")
    current = pipeline.current_run_id()
    for job in candidates:
        if job.get("run_id") == current:
            return job["run_id"], Path(job["path"])
    return candidates[0]["run_id"], Path(candidates[0]["path"])


def run(args, started, run_id, archive):
    out_dir = Path(args.out) if args.out else ROOT / "2-transcribe" / "output" / run_id / "targeted"
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = archive / "audio16k_full.wav"
    if not audio_path.is_file():
        raise SystemExit(f"missing audio: {audio_path}")
    print(f"[prototype] run_id={run_id}", flush=True)
    print(f"[prototype] audio={audio_path}", flush=True)
    print(f"[prototype] out={out_dir}", flush=True)

    meta_path = out_dir / "audio_tags.json"
    if args.rescan or not (archive / "audio_tags.json").is_file():
        meta = run_yamnet(audio_path, meta_path)
    else:
        shutil.copy2(archive / "audio_tags.json", meta_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        print("[prototype] reused archived audio_tags.json", flush=True)

    candidates_started = time.time()
    payload = build_candidates(
        meta,
        args.pre,
        args.post,
        args.merge_gap,
        args.limit,
        archive / "vad.json",
    )
    payload["run_id"] = run_id
    candidates_path = out_dir / "candidates.json"
    candidates_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    candidates_seconds = time.time() - candidates_started
    print(
        f"[prototype] candidates: {len(payload['candidates'])} "
        f"in {candidates_seconds:.1f}s",
        flush=True,
    )

    whisper_seconds = run_targeted_whisper(audio_path, out_dir, candidates_path)
    segments = json.loads((out_dir / "targeted_segments.json").read_text(encoding="utf-8"))
    words = json.loads((out_dir / "targeted_words.json").read_text(encoding="utf-8"))
    lines = build_event_lines(segments, meta)
    with open(out_dir / "targeted_with_events.json", "w", encoding="utf-8") as fh:
        json.dump(lines, fh, ensure_ascii=False, indent=1)
    with open(out_dir / "targeted_with_events.txt", "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(format_event_line(line) + "\n")

    api_key = llm_select.find_api_key(explicit_file=args.llm_api_key_file)
    base_url = llm_select.resolve_base_url(args.llm_base_url, api_key)
    if not args.no_llm:
        print(f"[prototype] Qwen endpoint={base_url}", flush=True)
    selections, llm_ready, llm_seconds = select_candidates(
        payload, lines, words, args, api_key, base_url
    )
    selection_payload = {
        "run_id": run_id,
        "video": json.loads((archive / "run.json").read_text(encoding="utf-8")).get("video"),
        "llm_ready": llm_ready,
        "selections": selections,
    }
    (out_dir / "selection.json").write_text(
        json.dumps(selection_payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    timings = {
        "run_id": run_id,
        "candidates": len(payload["candidates"]),
        "segments": len(segments),
        "words": len(words),
        "candidates_seconds": round(candidates_seconds, 1),
        "targeted_whisper_seconds": round(whisper_seconds, 1),
        "llm_seconds": round(llm_seconds, 1),
        "llm_ready": llm_ready,
        "total_seconds": round(time.time() - started, 1),
    }
    (out_dir / "timings.json").write_text(
        json.dumps(timings, indent=1), encoding="utf-8"
    )
    print(f"[prototype] selections: {len(selections)}", flush=True)
    print(f"[prototype] timings: {timings}", flush=True)
    return out_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--pre", type=float, default=float(config.get("targeted", "pre", 25.0)))
    parser.add_argument("--post", type=float, default=float(config.get("targeted", "post", 10.0)))
    parser.add_argument(
        "--merge-gap", type=float, default=float(config.get("targeted", "merge_gap", 5.0))
    )
    parser.add_argument("--limit", type=int, default=int(config.get("targeted", "limit", 0)))
    parser.add_argument("--rescan", action="store_true")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        default=not bool(config.get("targeted", "use_llm", True)),
    )
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--llm-base-url", default=llm_select.DEFAULT_BASE_URL)
    parser.add_argument("--llm-model", default=llm_select.DEFAULT_MODEL)
    parser.add_argument("--llm-api-key-file")
    parser.add_argument("--llm-timeout", type=float, default=llm_select.DEFAULT_TIMEOUT)
    args = parser.parse_args()

    started = time.time()
    run_id, archive = resolve_archive(args.run_id)
    if args.persist:
        pipeline.start_targeted_run(run_id)
    try:
        out_dir = run(args, started, run_id, archive)
    except Exception as exc:
        if args.persist:
            pipeline.mark_targeted_failed(run_id, exc)
        raise
    if args.persist:
        pipeline.update_targeted_after_run(run_id, out_dir)


if __name__ == "__main__":
    main()
