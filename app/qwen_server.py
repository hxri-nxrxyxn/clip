import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP_DIR))

import llm_select

import config


def _settings():
    section = config.section("qwen_server")
    return {
        "container": section.get("container", "unsloth"),
        "binary": section.get("binary", "/opt/unsloth/llama.cpp/llama-server"),
        "host": section.get("host", "0.0.0.0"),
        "port": int(section.get("port", 54301)),
        "startup_timeout": float(section.get("startup_timeout", 300.0)),
        "model": section.get("model", ""),
        "mmproj": section.get("mmproj", ""),
        "api_key_file": section.get("api_key_file", ""),
        "extra_args": [str(item) for item in section.get("extra_args", [])],
    }


def base_url(settings=None):
    settings = settings or _settings()
    return f"http://127.0.0.1:{settings['port']}"


def _ready(settings=None):
    settings = settings or _settings()
    return llm_select.server_ready(
        llm_select.resolve_base_url(base_url(settings), llm_select.find_api_key())
    )


def process_running(settings=None):
    settings = settings or _settings()
    pattern = f"{settings['binary']}.*--port {settings['port']}"
    try:
        result = subprocess.run(
            ["docker", "exec", settings["container"], "pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def stop(quiet=False):
    settings = _settings()
    pattern = f"{settings['binary']}.*--port {settings['port']}"
    try:
        subprocess.run(
            ["docker", "exec", settings["container"], "pkill", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    for _ in range(30):
        if not process_running(settings) and not _ready(settings):
            if not quiet:
                print(f"[qwen] stopped on port {settings['port']}")
            return True
        time.sleep(0.5)
    if not quiet:
        print(f"[qwen] stop requested on port {settings['port']}")
    return True


def start(quiet=False):
    settings = _settings()
    if _ready(settings):
        if not quiet:
            print(f"[qwen] already ready on port {settings['port']}")
        return True
    stop(quiet=True)
    if not settings["model"]:
        print("[qwen] no model configured", file=sys.stderr)
        return False
    alias = str(config.get("llm", "model", "qwen"))
    command = [
        settings["binary"],
        "-m",
        settings["model"],
        "--host",
        settings["host"],
        "--port",
        str(settings["port"]),
        "--alias",
        alias,
        *settings["extra_args"],
    ]
    if settings["mmproj"]:
        command.extend(["--mmproj", settings["mmproj"]])
    if settings["api_key_file"]:
        command.extend(["--api-key-file", settings["api_key_file"]])
    shell = " ".join(shlex.quote(item) for item in command)
    shell = f"nohup {shell} > /tmp/clip-qwen-server.log 2>&1 &"
    try:
        result = subprocess.run(
            ["docker", "exec", "-d", settings["container"], "sh", "-lc", shell],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[qwen] start failed: {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        print(f"[qwen] start failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    if not quiet:
        print(f"[qwen] starting on port {settings['port']}...")
    deadline = time.time() + settings["startup_timeout"]
    while time.time() < deadline:
        if _ready(settings):
            if not quiet:
                print(f"[qwen] ready on port {settings['port']}")
            return True
        if not process_running(settings):
            print("[qwen] process exited during startup", file=sys.stderr)
            return False
        time.sleep(1.0)
    print("[qwen] startup timed out", file=sys.stderr)
    return False


def ensure():
    settings = _settings()
    if _ready(settings):
        return True
    return start()


def status():
    settings = _settings()
    running = _ready(settings)
    process = process_running(settings)
    print(f"[qwen] port={settings['port']} ready={running} process={process}")
    return 0 if running else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "ensure", "status"])
    args = parser.parse_args()
    if args.command == "start":
        raise SystemExit(0 if start() else 1)
    if args.command == "stop":
        raise SystemExit(0 if stop() else 1)
    if args.command == "ensure":
        raise SystemExit(0 if ensure() else 1)
    raise SystemExit(status())


if __name__ == "__main__":
    main()
