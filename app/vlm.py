import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

import llm_select


def _image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _clamp_score(value: Any) -> int:
    try:
        return max(1, min(5, int(round(float(value)))))
    except (TypeError, ValueError):
        return 1


def analyze_contact_sheet(
    image_path: Path,
    clip: dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str | None,
    timeout: float,
    max_tokens: int,
) -> dict[str, Any]:
    transcript = clip.get("transcript") or ""
    prompt = f"""You are reviewing one contact sheet sampled chronologically from a short video clip.

Clip: {clip.get("candidate_id")}
Window: {float(clip.get("start", 0)):.1f}s to {float(clip.get("end", 0)):.1f}s
The frames are ordered left-to-right, top-to-bottom.
The timestamp of each frame is printed on the image.

Transcript context:
{transcript}

Describe what is visually happening in chronological order. Focus on visible action, reactions,
scene changes, and whether the frames are visually interesting. Do not invent details that are
not visible.

Return only JSON:
{{
  "summary": "one sentence describing the clip",
  "sequence": ["what happens first", "then", "finally"],
  "visual_score": 1,
  "transcript_support": 1,
  "flags": ["static", "facecam", "ui", "text", "dark", "fast_cut"],
  "reason": "short explanation"
}}

Scores are 1-5. visual_score measures visual interest/action. transcript_support measures how well
the visible action matches the transcript context."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a careful video visual analyst. Analyze only the supplied contact sheet. "
                "Return only valid JSON and do not use markdown."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": _image_data_url(image_path)},
                },
            ],
        },
    ]
    content = llm_select.chat(
        base_url,
        model,
        api_key,
        messages,
        timeout=timeout,
        max_tokens=max_tokens,
    )
    value = llm_select.extract_json(content)
    flags = value.get("flags") or []
    if not isinstance(flags, list):
        flags = [str(flags)]
    sequence = value.get("sequence") or []
    if not isinstance(sequence, list):
        sequence = [str(sequence)]
    return {
        "summary": str(value.get("summary", "")).strip(),
        "sequence": [str(item) for item in sequence],
        "visual_score": _clamp_score(value.get("visual_score")),
        "transcript_support": _clamp_score(value.get("transcript_support")),
        "flags": [str(item) for item in flags],
        "reason": str(value.get("reason", "")).strip(),
        "vlm_used": True,
    }


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "summary": "",
        "sequence": [],
        "visual_score": 0,
        "transcript_support": 0,
        "flags": [],
        "reason": reason,
        "vlm_used": False,
    }


def dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)
