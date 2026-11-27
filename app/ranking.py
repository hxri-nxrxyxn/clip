from typing import Any


def _score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _visual_score(value: Any) -> float:
    try:
        return max(0.0, min(5.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _duration_fit(seconds: float) -> float:
    if 8.0 <= seconds <= 30.0:
        return 1.0
    if 5.0 <= seconds <= 60.0:
        return 0.7
    if seconds > 0:
        return 0.4
    return 0.0


def _visual_by_candidate(visual: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not visual:
        return {}
    return {
        int(item.get("candidate_id")): item
        for item in visual.get("clips") or []
        if item.get("candidate_id") is not None
    }


def _rank_one(selection: dict[str, Any], visual: dict[str, Any] | None) -> dict[str, Any]:
    candidate_id = int(selection.get("candidate_id") or 0)
    start = float(selection.get("start") or 0)
    end = float(selection.get("end") or 0)
    duration = max(0.0, end - start)
    types = {
        str(key).upper(): _score(value)
        for key, value in (selection.get("types") or {}).items()
    }
    peak = _score(selection.get("peak_score"))
    visual_score = _visual_score((visual or {}).get("visual_score"))
    support = _visual_score((visual or {}).get("transcript_support"))
    visual_norm = visual_score / 5.0
    support_norm = support / 5.0
    laughter = types.get("LAUGHTER", 0.0)
    screaming = types.get("SCREAMING", 0.0)
    shouting = types.get("SHOUTING", 0.0)
    flags = {str(item).lower() for item in (visual or {}).get("flags") or []}
    penalty = min(0.12, 0.03 * len(flags & {"dark", "static", "text"}))

    funny = (
        0.38 * peak
        + 0.24 * visual_norm
        + 0.18 * support_norm
        + 0.20 * laughter
        - penalty
    )
    action = (
        0.32 * max(screaming, shouting)
        + 0.32 * visual_norm
        + 0.22 * peak
        + 0.14 * support_norm
        - penalty
    )
    match = 0.52 * peak + 0.48 * support_norm
    overall = (
        0.28 * peak
        + 0.24 * visual_norm
        + 0.20 * support_norm
        + 0.16 * laughter
        + 0.07 * action
        + 0.05 * _duration_fit(duration)
        - penalty
    )
    summary = (visual or {}).get("summary") or selection.get("reason") or ""
    return {
        "candidate_id": candidate_id,
        "start": start,
        "end": end,
        "duration": round(duration, 1),
        "overall": round(max(0.0, min(1.0, overall)) * 100, 1),
        "funny": round(max(0.0, min(1.0, funny)) * 100, 1),
        "action": round(max(0.0, min(1.0, action)) * 100, 1),
        "match": round(max(0.0, min(1.0, match)) * 100, 1),
        "visual_score": visual_score,
        "transcript_support": support,
        "events": ", ".join(sorted(types)),
        "summary": str(summary),
        "flags": sorted(flags),
        "visual_used": bool((visual or {}).get("vlm_used")),
    }


def build_rankings(
    selection: dict[str, Any] | None,
    visual: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not selection:
        return []
    visuals = _visual_by_candidate(visual)
    ranked = [
        _rank_one(item, visuals.get(int(item.get("candidate_id") or 0)))
        for item in selection.get("selections") or []
    ]
    ranked.sort(
        key=lambda item: (item["overall"], item["funny"], item["action"]),
        reverse=True,
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked
