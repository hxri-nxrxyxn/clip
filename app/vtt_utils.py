import math
import re
import textwrap


def hhmmss(seconds, floor=False):
    total = max(0, int(math.floor(seconds))) if floor else max(0, int(round(seconds)))
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
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap_text(text, width=42):
    wrapped = textwrap.wrap(
        text,
        width=width,
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
