import difflib
import json
import math
import re
import sys
import textwrap
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE = SCRIPT_DIR.parent
ROOT = STAGE.parent
OUT = STAGE / "output"

sys.path.insert(0, str(ROOT / "app"))
import config

CFG = config.section("merge_tags")
YAMNET = config.section("yamnet")

TAG_LABELS = {
    "LAUGHTER": "LAUGH",
    "SCREAMING": "SCREAM",
    "SHOUTING": "SHOUT",
}
TRIGGER_GROUPS = tuple(
    config.get("yamnet", "trigger_groups", ["LAUGHTER", "SCREAMING", "SHOUTING"])
)
TAG_ORDER = [(group, TAG_LABELS[group]) for group in TRIGGER_GROUPS if group in TAG_LABELS]

MEMBERSHIP = float(CFG.get("membership", YAMNET.get("tag_membership", 0.20)))
PEAK_FLOOR = float(CFG.get("peak_floor", YAMNET.get("peak_floor", 0.35)))
ABS_HIGH = float(CFG.get("abs_high", 0.60))
ABS_MED = float(CFG.get("abs_med", 0.45))
ABS_LOW = float(CFG.get("abs_low", 0.35))
MAX_BRIDGE = float(CFG.get("max_bridge", 7.0))
CHUNK_SECONDS = float(CFG.get("chunk_seconds", 600.0))
PERCENTILE_MIN_SPANS = int(CFG.get("percentile_min_spans", 8))

LOUD_GAP = float(CFG.get("loud_gap", 3.0))
MUSIC_THRESHOLD = float(CFG.get("music_threshold", YAMNET.get("music_threshold", 0.5)))
MUSIC_GAP = float(CFG.get("music_gap", 1.5))

PAUSE = float(CFG.get("pause", 0.7))
MAX_WORDS = int(CFG.get("max_words", 10))
MAX_LINE_SECONDS = float(CFG.get("max_line_seconds", 5.0))
MIN_CUE_SECONDS = float(CFG.get("min_cue_seconds", 0.5))
MAX_CUE_SECONDS = float(CFG.get("max_cue_seconds", 7.0))
TAG_ATTACH_LEAD = float(CFG.get("tag_attach_lead", 0.5))
VTT_WRAP_COLUMNS = int(CFG.get("vtt_wrap_columns", 42))

MAX_REPEAT = int(CFG.get("max_repeat", 2))
DUP_WINDOW = float(CFG.get("dup_window", 6.0))
DUP_RATIO = float(CFG.get("dup_ratio", 0.85))

LOW_CONF_P = float(CFG.get("low_conf_p", 0.15))
HIGH_CONF_P = float(CFG.get("high_conf_p", 0.5))
ISOLATION_WINDOW = float(CFG.get("isolation_window", 1.0))
MIN_WORD_DUR = float(CFG.get("min_word_dur", 0.08))
MAX_WORD_DUR = float(CFG.get("max_word_dur", 2.0))


def hhmmss(seconds, floor=False):
    if floor:
        total = max(0, int(math.floor(seconds)))
    else:
        total = max(0, int(round(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def interval(seconds_start, seconds_end):
    start = max(0, int(math.floor(seconds_start)))
    end = max(start + 1, int(math.floor(seconds_end)))
    return f"{hhmmss(start)}-{hhmmss(end)}"


def vtt_ts(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def vtt_escape(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def wrap_text(text):
    wrapped = textwrap.wrap(
        text,
        width=VTT_WRAP_COLUMNS,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return "\n".join(wrapped) if wrapped else text


def clean_join(parts):
    text = "".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def normalize_word(word):
    return re.sub(r"[^a-z0-9']", "", word.lower()).strip("'")


def normalize_text(text):
    text = re.sub(r"[^a-z0-9' ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def percentile(values, pct):
    if not values:
        return 1.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct / 100.0
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def filter_words(words):
    kept = []
    for word in words:
        duration = word["end"] - word["start"]
        if word["probability"] >= LOW_CONF_P:
            kept.append(word)
            continue
        if MIN_WORD_DUR <= duration <= MAX_WORD_DUR:
            kept.append(word)
            continue
        isolated = True
        for other in words:
            if other is word:
                continue
            if (
                other["probability"] >= HIGH_CONF_P
                and abs(other["start"] - word["start"]) <= ISOLATION_WINDOW
            ):
                isolated = False
                break
        if not isolated:
            kept.append(word)
    return kept


def sanitize_words(words, limit=None):
    cleaned = []
    for word in words:
        start = max(0.0, float(word["start"]))
        end = float(word["end"])
        if limit is not None:
            start = min(start, limit)
            end = min(end, limit)
        if end - start <= 0.0:
            end = start + MIN_WORD_DUR
        elif end - start > MAX_WORD_DUR:
            end = start + MAX_WORD_DUR
        cleaned.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "word": word["word"],
                "probability": word.get("probability", 0.0),
            }
        )
    return cleaned


def collapse_word_repeats(words):
    out = []
    run_key = None
    run_count = 0
    for word in words:
        key = normalize_word(word.get("word", ""))
        if key and key == run_key:
            run_count += 1
            if run_count > MAX_REPEAT:
                continue
        else:
            run_key = key or None
            run_count = 1
        out.append(word)
    return out


def build_lines(words, limit=None):
    lines = []
    cur = []
    last_end = 0.0

    def flush():
        nonlocal cur, last_end
        if not cur:
            return
        text = clean_join([w["word"] for w in cur])
        if text:
            start = max(float(cur[0]["start"]), last_end)
            end = max(float(cur[-1]["end"]), start + MIN_CUE_SECONDS)
            if limit is not None:
                end = min(end, limit)
            if end <= start:
                end = start + MIN_CUE_SECONDS
            lines.append(
                {"start": round(start, 3), "end": round(end, 3), "text": text}
            )
            last_end = lines[-1]["end"]
        cur = []

    for word in words:
        if not word.get("word"):
            continue
        if cur and (
            word["start"] - cur[-1]["end"] > PAUSE
            or word["end"] - cur[0]["start"] > MAX_LINE_SECONDS
        ):
            flush()
        cur.append(word)
        text = clean_join([w["word"] for w in cur])
        ends_sentence = bool(re.search(r"[.!?][\"')\]]?$", text))
        if (
            ends_sentence
            or len(cur) >= MAX_WORDS
            or word["end"] - cur[0]["start"] >= MAX_LINE_SECONDS
        ):
            flush()
    flush()
    return lines


def dedupe_lines(lines):
    out = []
    recent = []
    for line in lines:
        norm = normalize_text(line["text"])
        duplicate = False
        for prev_norm, prev_start in recent:
            if line["start"] - prev_start > DUP_WINDOW:
                continue
            ratio = difflib.SequenceMatcher(None, norm, prev_norm).ratio()
            substring = (
                min(len(norm), len(prev_norm)) >= 8
                and (norm in prev_norm or prev_norm in norm)
            )
            if ratio >= DUP_RATIO or substring:
                duplicate = True
                break
        if not duplicate:
            out.append(line)
            recent.append((norm, line["start"]))
            recent = [(n, s) for n, s in recent if line["start"] - s <= DUP_WINDOW]
    return out


def has_speech(start, end, words):
    return any(word["end"] > start and word["start"] < end for word in words)


def collapse_runs(points, threshold, window_seconds, max_gap):
    runs = []
    for start, score in points:
        if score < threshold:
            continue
        if runs and start - runs[-1]["last"] <= max_gap:
            runs[-1]["last"] = start
            runs[-1]["samples"].append((start, score))
        else:
            runs.append({"start": start, "last": start, "samples": [(start, score)]})
    for run in runs:
        run["end"] = run["last"] + window_seconds
    return runs


def clamp_span(start, end, limit):
    if limit is not None:
        start = min(start, limit)
        end = min(end, limit)
    return start, end


def build_spans(windows, group, words, limit=None):
    active = [w for w in windows if w["scores"][group] >= MEMBERSHIP]
    clusters = []
    cur = None
    for window in active:
        if cur is None:
            cur = [window]
            continue
        last = cur[-1]
        gap = window["start"] - last["end"]
        speech_between = any(
            last["end"] < word["start"] < window["start"] for word in words
        )
        if gap > MAX_BRIDGE or (group != "LAUGHTER" and speech_between):
            clusters.append(cur)
            cur = [window]
        else:
            cur.append(window)
    if cur:
        clusters.append(cur)

    spans = []
    for cluster in clusters:
        peak_window = max(cluster, key=lambda w: w["scores"][group])
        peak = peak_window["scores"][group]
        peak_time = peak_window["start"]
        start, end = clamp_span(cluster[0]["start"], cluster[-1]["end"], limit)
        if end <= start:
            continue
        overlap = [
            word for word in words if word["end"] > start and word["start"] < end
        ]
        spans.append(
            {
                "group": group,
                "start": start,
                "end": end,
                "peak": peak,
                "peak_time": min(peak_time, end),
                "overlapping_words": [word["word"].strip() for word in overlap],
                "speech_overlap": bool(overlap),
            }
        )
    return [span for span in spans if span["peak"] >= PEAK_FLOOR]


def classify(peak, chunk_peaks):
    if peak >= ABS_HIGH:
        return "high"
    if len(chunk_peaks) >= PERCENTILE_MIN_SPANS:
        if peak >= percentile(chunk_peaks, 97):
            return "high"
        if peak >= ABS_MED or peak >= percentile(chunk_peaks, 90):
            return "med"
        if peak >= ABS_LOW or peak >= percentile(chunk_peaks, 75):
            return "low"
        return "low"
    if peak >= ABS_MED:
        return "med"
    return "low"


def add_labels(spans):
    chunk_peaks = {}
    for span in spans:
        key = (span["group"], int(span["peak_time"] // CHUNK_SECONDS))
        chunk_peaks.setdefault(key, []).append(span["peak"])
    for span in spans:
        key = (span["group"], int(span["peak_time"] // CHUNK_SECONDS))
        span["label"] = classify(span["peak"], chunk_peaks[key])


def build_events(words, meta, limit=None):
    lines = dedupe_lines(build_lines(words, limit))
    windows = meta["windows"]

    spans = []
    for group, _ in TAG_ORDER:
        spans.extend(build_spans(windows, group, words, limit))
    add_labels(spans)

    events = [
        {
            "start": line["start"],
            "end": line["end"],
            "kind": "text",
            "text": line["text"],
        }
        for line in lines
    ]

    label_map = dict(TAG_ORDER)
    for span in spans:
        events.append(
            {
                "start": span["start"],
                "end": span["end"],
                "kind": "tag",
                "group": span["group"],
                "peak": span["peak"],
                "intensity": span["label"],
                "no_asr": not span["speech_overlap"],
                "no_asr_seconds": (
                    round(span["end"] - span["start"], 3)
                    if not span["speech_overlap"]
                    else 0.0
                ),
                "speech_over_laugh": span["group"] == "LAUGHTER"
                and span["speech_overlap"],
                "overlapping_words": span["overlapping_words"],
                "text": (
                    f"[{label_map[span['group']]} {span['label']} "
                    f"{span['peak']:.2f} peak "
                    f"{hhmmss(span['peak_time'], floor=True)}]"
                ),
            }
        )

    music_points = [(w["start"], w.get("music", 0.0)) for w in windows]
    for run in collapse_runs(
        music_points, MUSIC_THRESHOLD, meta["window_seconds"], MUSIC_GAP
    ):
        peak = max(score for _, score in run["samples"])
        start, end = clamp_span(run["start"], run["end"], limit)
        if end <= start:
            continue
        speech = has_speech(start, end, words)
        events.append(
            {
                "start": start,
                "end": end,
                "kind": "tag",
                "group": "MUSIC",
                "music_score": round(peak, 4),
                "speech_overlap": speech,
                "text": "[MUSIC under speech]" if speech else "[MUSIC]",
            }
        )

    loud_points = [(w["start"], w["rel_db"]) for w in windows]
    for run in collapse_runs(
        loud_points, meta["loud_db_threshold"], meta["window_seconds"], LOUD_GAP
    ):
        peak = max(score for _, score in run["samples"])
        start, end = clamp_span(run["start"], run["end"], limit)
        if end <= start:
            continue
        events.append(
            {
                "start": start,
                "end": end,
                "kind": "tag",
                "group": "LOUD",
                "peak_db": round(peak, 2),
                "text": f"[LOUD +{int(round(peak))}dB]",
            }
        )

    events.sort(key=lambda e: (e["start"], 0 if e["kind"] == "text" else 1))
    return lines, events


def write_txt(events):
    with open(OUT / "transcript_with_audio_tags.txt", "w", encoding="utf-8") as fh:
        for event in events:
            if event["kind"] == "tag":
                fh.write(f"[{interval(event['start'], event['end'])}] {event['text']}\n")
            else:
                fh.write(f"[{hhmmss(event['start'], floor=True)}] {event['text']}\n")


def merge_cues(cues):
    cues.sort(key=lambda cue: (cue["start"], 0 if cue["kind"] == "text" else 1))
    merged = []
    tolerance = 0.05
    for cue in cues:
        if merged and cue["start"] - merged[-1]["start"] <= tolerance:
            if cue["kind"] == "text" and merged[-1]["kind"] != "text":
                merged[-1]["text"] = cue["text"] + "\n" + merged[-1]["text"]
                merged[-1]["kind"] = "text"
            else:
                merged[-1]["text"] += "\n" + cue["text"]
            merged[-1]["end"] = max(merged[-1]["end"], cue["end"])
        else:
            merged.append(dict(cue))
    for cur, nxt in zip(merged, merged[1:]):
        if cur["end"] > nxt["start"]:
            cur["end"] = max(cur["start"] + 0.001, nxt["start"] - 0.001)
    return merged


def write_vtt(texts, tags, limit=None):
    cues = []
    attached = set()
    extras = [[] for _ in texts]

    for j, tag in enumerate(tags):
        for i, text in enumerate(texts):
            if text["start"] - TAG_ATTACH_LEAD <= tag["start"] < text["end"]:
                extras[i].append(tag["text"])
                attached.add(j)
                break

    for i, text in enumerate(texts):
        start = text["start"]
        end = max(text["end"], start + MIN_CUE_SECONDS)
        end = min(end, start + MAX_CUE_SECONDS)
        if limit is not None:
            end = min(end, limit)
        if end <= start:
            end = start + MIN_CUE_SECONDS
        body = vtt_escape(wrap_text(text["text"]))
        if extras[i]:
            body += "\n" + "\n".join(vtt_escape(tag) for tag in extras[i])
        cues.append({"start": start, "end": end, "kind": "text", "text": body})

    for j, tag in enumerate(tags):
        if j in attached:
            continue
        start = tag["start"]
        end = max(tag["end"], start + MIN_CUE_SECONDS)
        if limit is not None:
            end = min(end, limit)
        next_start = next(
            (text["start"] for text in texts if text["start"] > start), None
        )
        if next_start is not None:
            end = min(end, next_start - 0.001)
        if end <= start:
            end = start + MIN_CUE_SECONDS
        cues.append(
            {
                "start": start,
                "end": end,
                "kind": "tag",
                "text": vtt_escape(tag["text"]),
            }
        )

    cues = merge_cues(cues)
    with open(OUT / "transcript_with_audio_tags.vtt", "w", encoding="utf-8") as fh:
        fh.write("WEBVTT\n\n")
        for cue in cues:
            fh.write(f"{vtt_ts(cue['start'])} --> {vtt_ts(cue['end'])}\n")
            fh.write(cue["text"] + "\n\n")


def main():
    words = load_json(OUT / "whisper_words.json")
    meta = load_json(OUT / "audio_tags.json")
    limit = meta.get("duration_seconds")

    metadata_path = OUT / "metadata.json"
    if metadata_path.exists():
        cut = float(load_json(metadata_path)["trim_end_seconds"])
        limit = min(limit, cut) if limit is not None else cut
        words = [w for w in words if w["start"] < limit]

    words = filter_words(words)
    words = sanitize_words(words, limit)
    with open(OUT / "whisper_words_clean.json", "w", encoding="utf-8") as fh:
        json.dump(words, fh, ensure_ascii=False, separators=(",", ":"))

    words = collapse_word_repeats(words)
    lines, events = build_events(words, meta, limit)
    write_txt(events)
    texts = [event for event in events if event["kind"] == "text"]
    tags = [event for event in events if event["kind"] == "tag"]
    write_vtt(texts, tags, limit)

    with open(OUT / "transcript_with_audio_tags.json", "w", encoding="utf-8") as fh:
        json.dump(events, fh, ensure_ascii=False, indent=1)

    tag_lines = len(tags)
    print(
        f"[merge] {len(lines)} transcript lines, {tag_lines} audio-tag lines, "
        f"{len(events)} events"
    )


if __name__ == "__main__":
    main()
