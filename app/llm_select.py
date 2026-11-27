import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from app import config
else:
    import config

DEFAULT_BASE_URL = str(config.get("llm", "base_url", "http://127.0.0.1:38405"))
DEFAULT_MODEL = str(config.get("llm", "model", "unsloth/Qwen3.6-35B-A3B-MTP-GGUF"))
DEFAULT_TIMEOUT = float(config.get("llm", "timeout", 120.0))
MIN_CLIP = float(config.get("llm", "min_clip", 5.0))
MAX_CLIP = float(config.get("llm", "max_clip", 60.0))
HEURISTIC_RADIUS = float(config.get("llm", "heuristic_radius", 10.0))
MAX_TOKENS = int(config.get("llm", "max_tokens", 600))


def clock(seconds):
    total = max(0, int(round(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def _key_from_container(container=None):
    container = container or config.get("llm", "api_key_container", "unsloth")
    if not shutil.which("docker"):
        return None
    command = (
        "cat $(ls -t /opt/unsloth-studio/auth/llama_api_key_* 2>/dev/null | head -1) 2>/dev/null"
    )
    try:
        result = subprocess.run(
            ["docker", "exec", container, "sh", "-lc", command],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    key = result.stdout.strip()
    return key or None


def find_api_key(explicit_key=None, explicit_file=None, container=None):
    if explicit_key:
        return str(explicit_key).strip()
    if explicit_file:
        candidate = Path(explicit_file)
        if not candidate.is_absolute():
            candidate = config.ROOT / candidate
        try:
            key = candidate.read_text(encoding="utf-8").strip()
            if key:
                return key
        except OSError:
            pass
    key = str(config.get("llm", "api_key", "") or "").strip()
    if key:
        return key
    path = str(config.get("llm", "api_key_file", "") or "").strip()
    if path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = config.ROOT / candidate
        try:
            key = candidate.read_text(encoding="utf-8").strip()
            if key:
                return key
        except OSError:
            pass
    return _key_from_container(container)


def server_ready(base_url=DEFAULT_BASE_URL, api_key=None, timeout=3.0):
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    request = urllib.request.Request(f"{base_url.rstrip('/')}/health", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def container_ip(container=None):
    container = container or config.get("llm", "api_key_container", "unsloth")
    if not shutil.which("docker"):
        return None
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                container,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def resolve_base_url(base_url=None, api_key=None, container=None):
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if server_ready(base, api_key):
        return base
    parsed = urlsplit(base)
    if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        address = container_ip(container)
        if address:
            candidate = f"http://{address}:{parsed.port or 38405}"
            if server_ready(candidate, api_key):
                return candidate
    return base


def _extract_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except ValueError:
            pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    raise ValueError("no JSON object in LLM response")


def _chat(base_url, model, api_key, messages, timeout, max_tokens=None):
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens or MAX_TOKENS,
        "stream": False,
    }
    if config.get("llm", "disable_thinking", True):
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise
        payload["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    message = data["choices"][0]["message"]
    return message.get("content") or message.get("reasoning_content") or ""


def chat(
    base_url,
    model,
    api_key,
    messages,
    timeout=DEFAULT_TIMEOUT,
    max_tokens=None,
):
    return _chat(
        base_url,
        model,
        api_key,
        messages,
        timeout,
        max_tokens=max_tokens,
    )


extract_json = _extract_json


def _snap(start, end, window_start, window_end, words, peak_time):
    start = max(window_start, min(float(start), window_end))
    end = max(window_start, min(float(end), window_end))
    for word in words:
        if word["start"] < start < word["end"]:
            start = word["start"]
        if word["start"] < end < word["end"]:
            end = word["end"]
    if end - start < MIN_CLIP:
        end = min(window_end, start + MIN_CLIP)
        if end - start < MIN_CLIP:
            start = max(window_start, end - MIN_CLIP)
    if end - start > MAX_CLIP:
        end = start + MAX_CLIP
    start = max(window_start, min(start, window_end))
    end = max(start + 1.0, min(end, window_end))
    if peak_time < start or peak_time > end:
        pad = min(5.0, MIN_CLIP)
        start = max(window_start, min(start, peak_time - pad))
        end = min(window_end, max(end, peak_time + pad))
    return round(start, 3), round(end, 3)


def heuristic_clip(candidate, words):
    window_start = float(candidate["window_start"])
    window_end = float(candidate["window_end"])
    peak = float(candidate["peak_time"])
    start = max(window_start, peak - HEURISTIC_RADIUS)
    end = min(window_end, peak + HEURISTIC_RADIUS)
    start, end = _snap(start, end, window_start, window_end, words, peak)
    return {
        "start": start,
        "end": end,
        "reason": "peak-centered fallback",
        "llm_used": False,
    }


def select_clip(
    candidate,
    lines,
    words,
    base_url=DEFAULT_BASE_URL,
    model=DEFAULT_MODEL,
    api_key=None,
    timeout=DEFAULT_TIMEOUT,
):
    if not lines:
        return heuristic_clip(candidate, words)
    window_start = float(candidate["window_start"])
    window_end = float(candidate["window_end"])
    transcript = "\n".join(
        f"[{clock(line['start'])}-{clock(line['end'])}] "
        f"{' '.join(f'[{tag}]' for tag in line['tags'])} {line['text']}"
        for line in lines
    )
    system = (
        "You select the single most engaging clip from a transcript window. "
        "Return only a JSON object with keys start, end, reason. "
        "start and end are absolute seconds in the original video. "
        "Do not return markdown or commentary."
    )
    user = f"""Candidate window: {window_start:.3f}s to {window_end:.3f}s
Peak event time: {float(candidate["peak_time"]):.3f}s
Peak score: {float(candidate["peak_score"]):.3f}
Event types: {json.dumps(candidate.get("types", {}), sort_keys=True)}
Duration limit: {MIN_CLIP:g} to {MAX_CLIP:g} seconds.

Choose a clip that includes setup and payoff, avoids cutting sentences or words,
and starts before the peak and ends after it. Keep the result inside the window.

Transcript:
{transcript}

Return JSON only:
{{"start": 0.0, "end": 0.0, "reason": "..."}}"""
    content = _chat(
        base_url,
        model,
        api_key,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        timeout,
    )
    value = _extract_json(content)
    start = float(value["start"])
    end = float(value["end"])
    start, end = _snap(
        start,
        end,
        window_start,
        window_end,
        words,
        float(candidate["peak_time"]),
    )
    return {
        "start": start,
        "end": end,
        "reason": str(value.get("reason", "")).strip(),
        "llm_used": True,
    }
