import os
import random

import ctranslate2
import numpy as np
from faster_whisper import WhisperModel

MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
MODEL_REVISION = os.environ.get(
    "WHISPER_MODEL_REVISION", "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
)
SEED = int(os.environ.get("WHISPER_SEED", "1234"))
LOCAL_FILES_ONLY = os.environ.get("WHISPER_LOCAL_FILES_ONLY", "0") == "1"
TEMPERATURES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def seed_everything(seed=SEED):
    ctranslate2.set_random_seed(seed)
    random.seed(seed)
    np.random.seed(seed)


def load_model(model_dir):
    return WhisperModel(
        MODEL_NAME,
        device="cuda",
        compute_type="float16",
        download_root=model_dir,
        revision=MODEL_REVISION,
        local_files_only=LOCAL_FILES_ONLY,
    )


def decode_settings(log_prob_threshold):
    return {
        "language": "en",
        "task": "transcribe",
        "beam_size": 5,
        "temperature": TEMPERATURES,
        "compression_ratio_threshold": 3.5,
        "log_prob_threshold": log_prob_threshold,
        "no_repeat_ngram_size": 3,
        "condition_on_previous_text": False,
        "word_timestamps": True,
        "vad_filter": False,
    }


def collect_segments(model, audio, log_prob_threshold, progress=None):
    settings = decode_settings(log_prob_threshold)
    segments, info = model.transcribe(audio, **settings)
    out_segments = []
    words = []
    for seg in segments:
        seg_words = []
        for word in seg.words or []:
            if not word.word:
                continue
            item = {
                "start": round(float(word.start), 3),
                "end": round(float(word.end), 3),
                "word": word.word,
                "probability": round(float(word.probability), 4),
            }
            seg_words.append(item)
            words.append(item)
        out_segments.append(
            {
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
                "text": seg.text.strip(),
                "words": seg_words,
            }
        )
        if progress is not None:
            progress(seg, info)
    return out_segments, words, info
