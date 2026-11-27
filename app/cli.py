"""Command-line interface for the clip2 transcription and clipping pipeline."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from app import archive, layout, orchestrator, storage


def _wait(job_id: str) -> dict[str, Any] | None:
    while True:
        status = orchestrator.JOBS.get(job_id)
        if not status or status["status"] != "running":
            return status
        time.sleep(0.5)


def cmd_run(args: argparse.Namespace) -> int:
    """Run a specific stage or full pipeline."""
    stage = args.stage
    target = args.target
    run_id = args.run_id

    if stage in {"pipeline", "all"}:
        if not target:
            print("Error: target URL or file path required for full pipeline.", file=sys.stderr)
            return 2
        validated = orchestrator.validate_target(target)
        storage.archive_current_run()
        cmd = ["bash", str(storage.APP_DIR / "pipeline_job.sh"), validated]
        job = orchestrator.JOBS.start("pipeline", cmd)
        storage.set_current_job(job["id"], validated)
        print(f"Started pipeline job {job['id']} for {validated}")
        status = _wait(job["id"])
        if status and status["status"] == "succeeded":
            run_id = storage.archive_current_run()
            if run_id:
                storage.mark_current_run(run_id)
                storage.update_current_job("succeeded")
                print(f"Pipeline finished: {run_id}")
                return 0
        storage.update_current_job("failed")
        print("Pipeline failed.", file=sys.stderr)
        return 1

    if not run_id:
        run_id = storage.resolve_run_id()
    if not run_id:
        print(f"Error: no active or specified run_id for stage '{stage}'.", file=sys.stderr)
        return 2

    archive.prepare_stage_workspace(run_id, stage)
    cmd = ["bash", str(storage.APP_DIR / "stage_job.sh"), stage, run_id]
    if target:
        cmd.append(orchestrator.validate_target(target))
    job = orchestrator.JOBS.start(stage, cmd)
    storage.set_current_job(job["id"], target or "", run_id=run_id)
    print(f"Started stage '{stage}' job {job['id']} for run {run_id}")
    status = _wait(job["id"])
    if status:
        storage.update_current_job(status["status"])
        print(f"Stage '{stage}' finished: {status['status']}")
        return 0 if status["status"] == "succeeded" else 1
    return 1


def cmd_targeted(args: argparse.Namespace) -> int:
    """Run targeted clip selection for an archived run."""
    run_id = args.run_id or storage.resolve_run_id()
    if not run_id:
        print("Error: run_id required for targeted selection.", file=sys.stderr)
        return 2

    extra = []
    if args.no_llm:
        extra.append("--no-llm")
    if args.rescan:
        extra.append("--rescan")
    if args.limit:
        extra.extend(["--limit", str(args.limit)])

    print(f"Running targeted selection for run_id={run_id}...")
    try:
        res = archive.run_targeted_archive(run_id, extra_args=extra)
        if res:
            selections = res.get("selections", [])
            print(f"Targeted selection complete. Found {len(selections)} clip(s).")
        return 0
    except Exception as exc:
        print(f"Error running targeted selection: {exc}", file=sys.stderr)
        return 1


def cmd_handoff(args: argparse.Namespace) -> int:
    """Execute output handoff between stages."""
    try:
        res = orchestrator.handoff(args.from_stage, args.to_stage)
        print(f"Handoff succeeded: {res}")
        return 0
    except Exception as exc:
        print(f"Handoff failed: {exc}", file=sys.stderr)
        return 1


def cmd_layout(args: argparse.Namespace) -> int:
    """Run layout migration or cleanup."""
    if args.action == "migrate":
        layout.migrate(run_id=args.run_id, dry_run=args.dry_run)
    elif args.action == "cleanup":
        if args.all:
            layout.cleanup_all(dry_run=args.dry_run)
        elif args.run_id:
            layout.cleanup_run(args.run_id, dry_run=args.dry_run)
        else:
            print("Error: specify --run-id or --all for cleanup", file=sys.stderr)
            return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clip2", description="clip2 pipeline CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # run command
    p_run = sub.add_parser("run", help="Run a stage or full pipeline")
    p_run.add_argument("stage", choices=["pipeline", "all", "1-ingest", "2-transcribe", "3-select"])
    p_run.add_argument("--target", "-t", help="Target URL or local media filepath")
    p_run.add_argument("--run-id", "-r", help="Run ID for stage execution")
    p_run.set_defaults(func=cmd_run)

    # targeted command
    p_target = sub.add_parser("targeted", help="Execute targeted selection")
    p_target.add_argument("run_id", nargs="?", help="Run ID to process")
    p_target.add_argument("--no-llm", action="store_true", help="Disable LLM clip selection")
    p_target.add_argument(
        "--rescan", action="store_true", help="Force re-running YAMNet audio tagger"
    )
    p_target.add_argument("--limit", type=int, default=0, help="Limit number of candidate clips")
    p_target.set_defaults(func=cmd_targeted)

    # handoff command
    p_handoff = sub.add_parser("handoff", help="Handoff files between stages")
    p_handoff.add_argument("from_stage", help="Source stage ID")
    p_handoff.add_argument("to_stage", help="Destination stage ID")
    p_handoff.set_defaults(func=cmd_handoff)

    # layout command
    p_layout = sub.add_parser("layout", help="Organize or clean up job files")
    p_layout.add_argument("action", choices=["migrate", "cleanup"])
    p_layout.add_argument("--run-id", "-r", help="Target run ID")
    p_layout.add_argument("--all", action="store_true", help="Apply cleanup to all jobs")
    p_layout.add_argument(
        "--dry-run", action="store_true", help="Simulate without modifying filesystem"
    )
    p_layout.set_defaults(func=cmd_layout)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
