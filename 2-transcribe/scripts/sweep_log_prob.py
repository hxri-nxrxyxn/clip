import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE = SCRIPT_DIR.parent
ROOT = STAGE.parent
IN = STAGE / "input"
OUT = STAGE / "output"
TESTS = SCRIPT_DIR / "tests"
CLIPS_DIR = TESTS / "clips"
SPEC = TESTS / "clips.json"
AUDIO_FULL = IN / "audio16k_full.wav"
AUDIO_TAGS = OUT / "audio_tags.json"
COMPOSE = STAGE / "services" / "whisper" / "docker-compose.yml"
DEFAULT_THRESHOLDS = [-1.0, -0.6, -0.4]


def parse_time(value):
    if isinstance(value, (int, float)):
        return float(value)
    total = 0.0
    for part in str(value).split(":"):
        total = total * 60 + float(part)
    return total


def wav_duration(path):
    with wave.open(str(path), "rb") as fh:
        return fh.getnframes() / fh.getframerate()


def prepare_clips():
    spec = json.load(open(SPEC, encoding="utf-8"))
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    duration = wav_duration(AUDIO_FULL)
    pad = float(spec.get("pad_seconds", 1.0))

    for clip in spec["positive"]:
        start = max(0.0, parse_time(clip["start"]) - pad)
        end = min(duration, parse_time(clip["end"]) + pad)
        out = CLIPS_DIR / f"{clip['id']}.wav"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                "-i", str(AUDIO_FULL), "-c:a", "pcm_s16le", str(out),
            ],
            check=True,
        )
        print(f"[clips] {clip['id']} {start:.1f}-{end:.1f}s -> {out.name}")

    for clip in spec.get("negative", []):
        out = CLIPS_DIR / f"{clip['id']}.wav"
        if clip.get("type") == "silence":
            frames = int(float(clip.get("duration", 6.0)) * 16000)
            with wave.open(str(out), "wb") as fh:
                fh.setnchannels(1)
                fh.setsampwidth(2)
                fh.setframerate(16000)
                fh.writeframes(b"\x00\x00" * frames)
            print(f"[clips] {clip['id']} silence {frames / 16000:.1f}s -> {out.name}")


def run_one(threshold, runs):
    results_path = TESTS / f"sweep_{threshold:+.1f}.json"
    cmd = [
        "docker", "compose", "-f", str(COMPOSE), "run", "--rm", "--no-deps",
        "-w", "/work",
        "-e", f"SWEEP_THRESHOLD={threshold}",
        "-e", f"SWEEP_RUNS={runs}",
        "-e", "AUDIO=/work/input/audio16k_full.wav",
        "-e", "CLIPS_SPEC=/work/scripts/tests/clips.json",
        "-e", f"RESULTS_JSON=/work/scripts/tests/sweep_{threshold:+.1f}.json",
        "-e", "AUDIO_TAGS_JSON=/work/output/audio_tags.json",
        "whisper", "python3", "/work/scripts/sweep_runner.py",
    ]
    print(f"[sweep] threshold {threshold} ...", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
    return json.load(open(results_path, encoding="utf-8"))


def cell(count, runs):
    return f"{count}/{runs}"


def print_table(results, runs):
    print()
    print("threshold | p1 | p2 | p3 | n1 | all-pass runs | hallucinations")
    print("----------+----+----+----+----+---------------+---------------")
    for res in results:
        s = res["summary"]
        p = s["positive_pass_counts"]
        n = s["negative_pass_counts"]
        cells = [
            cell(p.get("p1", 0), runs),
            cell(p.get("p2", 0), runs),
            cell(p.get("p3", 0), runs),
            cell(next(iter(n.values()), 0), runs) if n else "-",
            f"{s['all_pass_runs']}/{runs}",
            str(s["total_hallucinations"]),
        ]
        print(f"{res['threshold']:>9} | " + " | ".join(cells))


def select(results):
    consistent = [r for r in results if r["summary"]["fully_consistent"]]
    if consistent:
        chosen = min(
            consistent,
            key=lambda r: (r["summary"]["total_hallucinations"], abs(r["threshold"] + 0.6)),
        )
        return chosen, "fully_consistent"
    rate = [r for r in results if r["summary"].get("rate_pass")]
    if rate:
        chosen = min(
            rate,
            key=lambda r: (r["summary"]["total_hallucinations"], abs(r["threshold"] + 0.6)),
        )
        return chosen, "rate_pass"
    chosen = max(
        results,
        key=lambda r: (r["summary"]["all_pass_runs"], -r["summary"]["total_hallucinations"]),
    )
    return chosen, "best_effort"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--thresholds", nargs="+", type=float, default=None)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--skip-full", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    prepare_clips()

    if args.test:
        selected_file = IN / "selected_threshold.txt"
        if args.thresholds:
            thresholds = args.thresholds
        elif selected_file.exists():
            thresholds = [float(selected_file.read_text().strip())]
        else:
            raise SystemExit("no selected threshold; run the sweep first")
        results = [run_one(thresholds[0], args.runs)]
        res = results[0]
        print_table(results, args.runs)
        summary = res["summary"]
        if summary.get("rate_pass"):
            if summary.get("fully_consistent"):
                print("[test] PASS: all golden clips consistent (N/N)")
            else:
                print(
                    f"[test] PASS (rate rule >= {summary['rate_min']}/{args.runs}): "
                    f"{summary['positive_pass_counts']} {summary['negative_pass_counts']}"
                )
            return
        print(f"[test] FAIL: {summary}")
        sys.exit(1)

    thresholds = args.thresholds or DEFAULT_THRESHOLDS
    results = [run_one(t, args.runs) for t in thresholds]
    print_table(results, args.runs)

    chosen, status = select(results)
    if status == "fully_consistent":
        print(f"[sweep] selected threshold {chosen['threshold']} (fully consistent)")
    elif status == "rate_pass":
        print(
            f"[sweep] selected threshold {chosen['threshold']} "
            f"(rate_pass >= {chosen['summary']['rate_min']}/{args.runs}; "
            f"not fully consistent)"
        )
    else:
        print(
            f"[sweep] WARNING: no threshold passed the rate rule; "
            f"best-effort selection {chosen['threshold']}"
        )

    combined = {
        "runs": args.runs,
        "results": results,
        "selected_threshold": chosen["threshold"],
        "selection_status": status,
    }
    with open(TESTS / "sweep_results.json", "w", encoding="utf-8") as fh:
        json.dump(combined, fh, ensure_ascii=False, indent=1)
    (IN / "selected_threshold.txt").write_text(f"{chosen['threshold']}\n")
    print(f"[sweep] results -> {TESTS / 'sweep_results.json'}")


if __name__ == "__main__":
    main()
