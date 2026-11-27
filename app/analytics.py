import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config


def clock(seconds):
    total = max(0, int(round(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def calculate_activity(meta, words, bin_seconds=10):
    if not isinstance(meta, dict) or not meta.get("windows"):
        return None
    windows = meta["windows"]
    duration = float(
        meta.get("duration_seconds")
        or max(float(window["end"]) for window in windows)
    )
    if duration <= 0:
        return None
    bin_seconds = max(1, int(bin_seconds))
    count = max(1, math.ceil(duration / bin_seconds))
    bins = []
    for index in range(count):
        start = index * bin_seconds
        bins.append(
            {
                "index": index,
                "start": start,
                "end": min(start + bin_seconds, duration),
                "time": clock(start),
                "windows": 0,
                "words": 0,
                "loud": 0,
                "rel_db": 0.0,
                "laugh": 0.0,
                "scream": 0.0,
                "shout": 0.0,
                "music": 0.0,
            }
        )

    loud_threshold = float(config.get("yamnet", "loud_db", 6.0))
    for window in windows:
        center = (float(window["start"]) + float(window["end"])) / 2
        index = min(int(center // bin_seconds), count - 1)
        item = bins[index]
        item["windows"] += 1
        item["rel_db"] += float(window.get("rel_db", 0.0))
        scores = window.get("scores") or {}
        item["laugh"] = max(item["laugh"], float(scores.get("LAUGHTER", 0.0)))
        item["scream"] = max(item["scream"], float(scores.get("SCREAMING", 0.0)))
        item["shout"] = max(item["shout"], float(scores.get("SHOUTING", 0.0)))
        item["music"] = max(item["music"], float(window.get("music", 0.0)))
        if float(window.get("rel_db", -999.0)) >= loud_threshold:
            item["loud"] += 1

    for word in words or []:
        if not isinstance(word, dict) or "start" not in word:
            continue
        index = min(int(float(word["start"]) // bin_seconds), count - 1)
        bins[index]["words"] += 1

    for item in bins:
        windows_in_bin = item["windows"] or 1
        item["rel_db"] = item["rel_db"] / windows_in_bin
        item["loud"] = item["loud"] / windows_in_bin
        item["speech"] = item["words"] / bin_seconds

    metrics = [
        ("Loudness", "rel_db", "minmax"),
        ("Speech", "speech", "max"),
        ("Loud", "loud", "fixed"),
        ("Laughter", "laugh", "fixed"),
        ("Screaming", "scream", "fixed"),
        ("Shouting", "shout", "fixed"),
        ("Music", "music", "fixed"),
    ]
    heatmap = []
    for label, key, mode in metrics:
        values = [float(item[key]) for item in bins]
        if mode == "minmax":
            low, high = min(values), max(values)
            span = high - low if high > low else 1.0
            normalized = [(value - low) / span for value in values]
        elif mode == "max":
            high = max(values) or 1.0
            normalized = [value / high for value in values]
        else:
            normalized = [max(0.0, min(1.0, value)) for value in values]
        for item, value in zip(bins, normalized):
            heatmap.append(
                {
                    "time": item["time"],
                    "index": item["index"],
                    "metric": label,
                    "value": round(float(value), 4),
                    "raw": round(float(item[key]), 3),
                }
            )

    minute_count = max(1, math.ceil(duration / 60.0))
    minutes = []
    for index in range(minute_count):
        start = index * 60.0
        end = min(start + 60.0, duration)
        selected = [item for item in bins if item["start"] < end and item["end"] > start]
        weighted = [item for item in selected if item["windows"]]
        rel_db = (
            sum(item["rel_db"] * item["windows"] for item in weighted)
            / sum(item["windows"] for item in weighted)
            if weighted
            else 0.0
        )
        minutes.append(
            {
                "time": clock(start),
                "start": start,
                "words": sum(item["words"] for item in selected),
                "loud": round(sum(item["loud"] for item in selected), 2),
                "laugh": round(max((item["laugh"] for item in selected), default=0.0), 3),
                "scream": round(max((item["scream"] for item in selected), default=0.0), 3),
                "shout": round(max((item["shout"] for item in selected), default=0.0), 3),
                "music": round(max((item["music"] for item in selected), default=0.0), 3),
                "rel_db": round(rel_db, 2),
            }
        )
    max_words = max((item["words"] for item in minutes), default=0) or 1
    max_loud = max((item["loud"] for item in minutes), default=0) or 1
    for item in minutes:
        item["activity"] = round(
            item["words"] / max_words
            + item["loud"] / max_loud
            + max(item["laugh"], item["scream"], item["shout"])
            + item["music"],
            3,
        )

    tag_membership = float(config.get("yamnet", "tag_membership", 0.2))
    totals = {
        "duration": round(duration, 1),
        "words": len(words or []),
        "loud_windows": sum(
            1
            for window in windows
            if float(window.get("rel_db", -999.0)) >= loud_threshold
        ),
        "laughter_windows": sum(
            1
            for window in windows
            if float((window.get("scores") or {}).get("LAUGHTER", 0.0)) >= tag_membership
        ),
        "screaming_windows": sum(
            1
            for window in windows
            if float((window.get("scores") or {}).get("SCREAMING", 0.0)) >= tag_membership
        ),
        "shouting_windows": sum(
            1
            for window in windows
            if float((window.get("scores") or {}).get("SHOUTING", 0.0)) >= tag_membership
        ),
        "music_windows": sum(
            1
            for window in windows
            if float(window.get("music", 0.0)) >= 0.5
        ),
    }
    return {
        "duration": round(duration, 1),
        "bin_seconds": bin_seconds,
        "bins": bins,
        "heatmap": heatmap,
        "minutes": minutes,
        "totals": totals,
    }
