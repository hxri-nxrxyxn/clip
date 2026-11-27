import datetime
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
RUNS_DIR = APP_DIR / "runs"


class Jobs:
    def __init__(self, runs_dir=RUNS_DIR, root_dir=ROOT):
        self.runs_dir = Path(runs_dir)
        self.root_dir = Path(root_dir)
        self.lock = threading.Lock()
        self.jobs = {}
        self.processes = {}
        self.active = None
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def tail(self, path, max_bytes=20000, max_lines=200):
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - max_bytes))
                text = fh.read().decode("utf-8", "replace")
            return "\n".join(text.splitlines()[-max_lines:])
        except OSError:
            return ""

    def public(self, job):
        if not job:
            return None
        end = job["ended"] or time.time()
        return {
            "id": job["id"],
            "stage": job["stage"],
            "status": job["status"],
            "returncode": job["returncode"],
            "elapsed": round(end - job["started"], 1),
            "log_tail": self.tail(job["log_path"]),
        }

    def start(self, stage_id, argv):
        with self.lock:
            if self.active and self.jobs[self.active]["status"] == "running":
                raise RuntimeError("another job is already running")
            job_id = uuid.uuid4().hex[:12]
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            log_path = self.runs_dir / f"{stamp}-{stage_id}-{job_id}.log"
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
                process = subprocess.Popen(
                    argv,
                    cwd=str(self.root_dir),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                    env=env,
                )
            job = {
                "id": job_id,
                "stage": stage_id,
                "status": "running",
                "started": time.time(),
                "ended": None,
                "returncode": None,
                "log_path": str(log_path),
            }
            self.jobs[job_id] = job
            self.processes[job_id] = process
            self.active = job_id
            data = self.public(job)
        threading.Thread(target=self._wait, args=(job_id, process), daemon=True).start()
        return data

    def _wait(self, job_id, process):
        returncode = process.wait()
        with self.lock:
            job = self.jobs[job_id]
            job["returncode"] = returncode
            job["ended"] = time.time()
            job["status"] = "succeeded" if returncode == 0 else "failed"
            if self.active == job_id:
                self.active = None
            self.processes.pop(job_id, None)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return self.public(job) if job else None

    def latest(self, stage_id):
        with self.lock:
            result = None
            for job in self.jobs.values():
                if job["stage"] == stage_id and (
                    result is None or job["started"] > result["started"]
                ):
                    result = job
            return self.public(result) if result else None

    def current(self):
        with self.lock:
            job = self.jobs.get(self.active) if self.active else None
            return self.public(job) if job else None


JOBS = Jobs()
