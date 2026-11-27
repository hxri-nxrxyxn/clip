import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pipeline

APP_DIR = Path(__file__).resolve().parent
ROOT = pipeline.ROOT


def path_size(path):
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def move_path(source, destination, dry_run=False):
    if not source.exists():
        return 0
    if source.is_dir():
        total = 0
        for child in sorted(source.iterdir()):
            if child.name == ".gitkeep":
                continue
            total += move_path(child, destination / child.name, dry_run)
        if not any(source.iterdir()):
            if not dry_run:
                source.rmdir()
        return total
    if destination.exists():
        print(f"skip (exists): {source} -> {destination}")
        return 0
    total = path_size(source)
    print(f"{'would move' if dry_run else 'move'}: {source} -> {destination}")
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    return total


def migrate(run_id=None, dry_run=False):
    resolved = pipeline.resolve_run_id(run_id)
    if not resolved:
        raise SystemExit("could not resolve run_id")
    archive = pipeline.HISTORY_DIR / resolved
    if not (archive / "run.json").is_file():
        raise SystemExit(f"history entry not found: {resolved}")
    print(f"[layout] migrating {resolved}")
    moved = 0
    ingest_root = ROOT / "1-ingest" / "output"
    ingest_job = pipeline.stage_output_dir("1-ingest", resolved)
    for name in ("ingest.json", "source.info.json", "audio"):
        moved += move_path(ingest_root / name, ingest_job / name, dry_run)
    moved += move_path(
        ROOT / "2-transcribe" / "input" / "audio16k_full.wav",
        pipeline.stage_input_dir("2-transcribe", resolved) / "audio16k_full.wav",
        dry_run,
    )
    transcribe_root = ROOT / "2-transcribe" / "output"
    transcribe_job = pipeline.stage_output_dir("2-transcribe", resolved)
    for child in sorted(transcribe_root.iterdir()):
        if child.name in {".gitkeep", resolved}:
            continue
        moved += move_path(child, transcribe_job / child.name, dry_run)
    legacy_targeted = APP_DIR / "prototype" / resolved
    if legacy_targeted.is_dir():
        moved += move_path(legacy_targeted, transcribe_job / "targeted", dry_run)
    if not dry_run:
        pipeline.write_current_run_pointer(resolved)
    print(f"[layout] {'would move' if dry_run else 'moved'} {moved / 1024 / 1024:.1f} MB")
    return resolved


def cleanup_paths(run_id):
    paths = [APP_DIR / "prototype" / run_id]
    for stage_id in pipeline.STAGE_IDS:
        paths.append(pipeline.stage_input_dir(stage_id, run_id))
        paths.append(pipeline.stage_output_dir(stage_id, run_id))
    return paths


def cleanup_run(run_id, dry_run=False, force=False):
    archive = pipeline.HISTORY_DIR / run_id
    if not (archive / "run.json").is_file() and not force:
        print(f"skip (no archive): {run_id}")
        return 0
    marker = pipeline.current_job() or {}
    if marker.get("run_id") == run_id and marker.get("status") == "running" and not force:
        print(f"skip (running): {run_id}")
        return 0
    total = 0
    for path in cleanup_paths(run_id):
        if not path.exists():
            continue
        total += path_size(path)
        print(f"{'would remove' if dry_run else 'remove'}: {path}")
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    print(f"[cleanup] {run_id}: {'would free' if dry_run else 'freed'} {total / 1024 / 1024:.1f} MB")
    return total


def cleanup_all(dry_run=False, force=False):
    if not pipeline.HISTORY_DIR.is_dir():
        return 0
    total = 0
    for path in sorted(pipeline.HISTORY_DIR.iterdir()):
        if not (path / "run.json").is_file():
            continue
        total += cleanup_run(path.name, dry_run=dry_run, force=force)
    return total


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    migrate_parser = sub.add_parser("migrate")
    migrate_parser.add_argument("--run-id")
    migrate_parser.add_argument("--dry-run", action="store_true")
    cleanup_parser = sub.add_parser("cleanup")
    cleanup_parser.add_argument("--run-id")
    cleanup_parser.add_argument("--all", action="store_true")
    cleanup_parser.add_argument("--dry-run", action="store_true")
    cleanup_parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "migrate":
        migrate(args.run_id, args.dry_run)
    elif args.command == "cleanup":
        if args.all:
            cleanup_all(args.dry_run, args.force)
        elif args.run_id:
            cleanup_run(args.run_id, args.dry_run, args.force)
        else:
            raise SystemExit("cleanup needs --run-id or --all")


if __name__ == "__main__":
    main()
