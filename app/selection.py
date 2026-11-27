import argparse
import json
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP_DIR))

import llm_select
import pipeline


def format_event_line(line):
    tags = "".join(f"[{tag}]" for tag in line["tags"])
    return f"[{pipeline.clock(line['start'])}] {tags} {line['text']}".replace("]  ", "] ")


def load_extraction(run_id):
    candidates = [
        pipeline.stage_output_dir("2-transcribe", run_id) / "targeted",
        pipeline.HISTORY_DIR / run_id / "targeted",
    ]
    source = next((path for path in candidates if (path / "candidates.json").is_file()), None)
    if source is None:
        raise SystemExit(
            f"targeted extraction missing for {run_id}; run targeted extraction on Transcribe first"
        )
    return {
        "path": source,
        "candidates": json.loads((source / "candidates.json").read_text(encoding="utf-8")),
        "lines": json.loads((source / "targeted_with_events.json").read_text(encoding="utf-8")),
        "words": json.loads((source / "targeted_words.json").read_text(encoding="utf-8")),
    }


def select_candidates(payload, lines, words, args, api_key, base_url):
    llm_ready = False
    if not args.no_llm:
        llm_ready = llm_select.server_ready(base_url, api_key)
        print(
            f"[select] Qwen {'available' if llm_ready else 'unavailable; using fallback'}",
            flush=True,
        )
    selections = []
    llm_seconds = 0.0
    for candidate in payload["candidates"]:
        window_start = float(candidate["window_start"])
        window_end = float(candidate["window_end"])
        candidate_lines = [
            line for line in lines if line["end"] > window_start and line["start"] < window_end
        ]
        candidate_words = [
            word for word in words if word["end"] > window_start and word["start"] < window_end
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
                print(f"[select] LLM failed for candidate {candidate['id']}: {exc}", flush=True)
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


def run(args, started, run_id, archive):
    out_dir = Path(args.out) if args.out else ROOT / "3-select" / "output" / run_id
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    extraction = load_extraction(run_id)
    payload = extraction["candidates"]
    print(f"[select] run_id={run_id}", flush=True)
    print(f"[select] source={extraction['path']}", flush=True)
    print(f"[select] out={out_dir}", flush=True)

    api_key = llm_select.find_api_key(explicit_file=args.llm_api_key_file)
    base_url = llm_select.resolve_base_url(args.llm_base_url, api_key)
    if not args.no_llm:
        print(f"[select] Qwen endpoint={base_url}", flush=True)
    selections, llm_ready, llm_seconds = select_candidates(
        payload, extraction["lines"], extraction["words"], args, api_key, base_url
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
        "candidates": len(payload.get("candidates") or []),
        "selections": len(selections),
        "llm_seconds": round(llm_seconds, 1),
        "llm_ready": llm_ready,
        "total_seconds": round(time.time() - started, 1),
    }
    (out_dir / "timings.json").write_text(json.dumps(timings, indent=1), encoding="utf-8")
    print(f"[select] selections: {len(selections)}", flush=True)
    print(f"[select] timings: {timings}", flush=True)
    return out_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--llm-base-url", default=llm_select.DEFAULT_BASE_URL)
    parser.add_argument("--llm-model", default=llm_select.DEFAULT_MODEL)
    parser.add_argument("--llm-api-key-file")
    parser.add_argument("--llm-timeout", type=float, default=llm_select.DEFAULT_TIMEOUT)
    args = parser.parse_args()

    started = time.time()
    run_id = pipeline.resolve_run_id(args.run_id)
    if not run_id:
        raise SystemExit("missing run_id")
    archive = pipeline.HISTORY_DIR / run_id
    if not (archive / "run.json").is_file():
        raise SystemExit(f"history entry not found: {run_id}")
    if args.persist:
        pipeline.start_selection_run(run_id)
    try:
        out_dir = run(args, started, run_id, archive)
    except Exception as exc:
        if args.persist:
            pipeline.mark_selection_failed(run_id, exc)
        raise
    if args.persist:
        pipeline.update_selection_after_run(run_id, out_dir)


if __name__ == "__main__":
    main()
