import re

PROFANITY = {
    "fucking", "fuckin", "fuking", "fukin", "fcking", "fckin",
    "freaking", "fricking", "frigging", "fing", "fin",
}


def canon_token(token):
    if token in PROFANITY:
        return "fucking"
    if (
        token.startswith("f")
        and ("ck" in token or "kk" in token or "k" in token)
        and token.endswith(("ing", "in", "n", "g"))
    ):
        return "fucking"
    return token


def tokens(text):
    out = []
    for raw in re.findall(r"[a-zA-Z0-9']+", text.lower()):
        token = raw.strip("'")
        out.append(canon_token(token))
    return out


def levenshtein(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def phrase_in(phrase, transcript):
    target = tokens(phrase)
    source = tokens(transcript)
    if not target:
        return True
    max_edits = 1 if len(target) <= 3 else 2
    for width in range(max(1, len(target) - 1), len(target) + 2):
        for i in range(0, max(1, len(source) - width + 1)):
            if levenshtein(target, source[i : i + width]) <= max_edits:
                return True
    return False


def repeated_ngram_count(transcript, max_repeat=2):
    seq = tokens(transcript)
    events = 0
    for n in (1, 2, 3):
        i = 0
        while i + n <= len(seq):
            reps = 1
            j = i + n
            while j + n <= len(seq) and seq[j : j + n] == seq[i : i + n]:
                reps += 1
                j += n
            if reps > max_repeat:
                events += 1
                i = j
            else:
                i += 1
    return events


def low_conf_isolated_count(
    words, low_p=0.15, high_p=0.5, window=1.0, min_dur=0.08, max_dur=2.0
):
    count = 0
    for word in words:
        if word["probability"] >= low_p:
            continue
        duration = word["end"] - word["start"]
        if min_dur <= duration <= max_dur:
            continue
        isolated = True
        for other in words:
            if other is word:
                continue
            if (
                other["probability"] >= high_p
                and abs(other["start"] - word["start"]) <= window
            ):
                isolated = False
                break
        if isolated:
            count += 1
    return count


def words_in_noise_count(words, windows, threshold_db=-50.0, p_max=0.5):
    count = 0
    for word in words:
        if word["probability"] >= p_max:
            continue
        overlapping = [
            w for w in windows if w["end"] > word["start"] and w["start"] < word["end"]
        ]
        if overlapping and all(w["rms_db"] < threshold_db for w in overlapping):
            count += 1
    return count
