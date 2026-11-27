import argparse
import json
import shlex
from copy import deepcopy
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "local.toml"

DEFAULTS = {
    "targeted": {
        "pre": 25.0,
        "post": 10.0,
        "merge_gap": 5.0,
        "limit": 0,
        "use_llm": True,
        "quiet_rel_db": -6.0,
        "snap_max_shift": 5.0,
        "music_threshold": 0.5,
    },
    "llm": {
        "base_url": "http://127.0.0.1:38405",
        "model": "unsloth/Qwen3.6-35B-A3B-MTP-GGUF",
        "timeout": 120.0,
        "disable_thinking": True,
        "max_tokens": 600,
        "min_clip": 5.0,
        "max_clip": 60.0,
        "heuristic_radius": 10.0,
        "api_key": "",
        "api_key_file": "",
        "api_key_container": "unsloth",
    },
    "whisper": {
        "model": "large-v3-turbo",
        "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        "log_prob_threshold": -0.4,
        "seed": 1234,
        "local_files_only": False,
    },
    "yamnet": {
        "sample_rate": 16000,
        "window": 16000,
        "hop": 8000,
        "yamnet_samples": 15600,
        "tag_membership": 0.20,
        "peak_floor": 0.35,
        "loud_db": 6.0,
        "music_threshold": 0.5,
        "music_index": 132,
        "trigger_groups": ["LAUGHTER", "SCREAMING", "SHOUTING"],
        "model": "2-transcribe/services/yamnet/yamnet.tflite",
        "class_map": "2-transcribe/services/yamnet/yamnet_class_map.csv",
    },
    "merge_tags": {
        "membership": 0.20,
        "peak_floor": 0.35,
        "abs_high": 0.60,
        "abs_med": 0.45,
        "abs_low": 0.35,
        "max_bridge": 7.0,
        "chunk_seconds": 600.0,
        "percentile_min_spans": 8,
        "loud_gap": 3.0,
        "music_threshold": 0.5,
        "music_gap": 1.5,
        "pause": 0.7,
        "max_words": 10,
        "max_line_seconds": 5.0,
        "min_cue_seconds": 0.5,
        "max_cue_seconds": 7.0,
        "tag_attach_lead": 0.5,
        "vtt_wrap_columns": 42,
        "max_repeat": 2,
        "dup_window": 6.0,
        "dup_ratio": 0.85,
        "low_conf_p": 0.15,
        "high_conf_p": 0.5,
        "isolation_window": 1.0,
        "min_word_dur": 0.08,
        "max_word_dur": 2.0,
    },
    "outro": {
        "tail_seconds": 2.0,
        "confidence_threshold": 0.05,
    },
}


def config_path():
    return CONFIG_PATH


def _read_toml(path):
    if not path.is_file():
        return {}
    if tomllib is None:
        raise RuntimeError("TOML support is unavailable; install tomli")
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _merge(base, overlay):
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _validate(config):
    targeted = config.get("targeted", {})
    llm = config.get("llm", {})
    whisper = config.get("whisper", {})
    if float(targeted.get("pre", 0)) < 0:
        raise ValueError("targeted.pre must be >= 0")
    if float(targeted.get("post", 0)) < 0:
        raise ValueError("targeted.post must be >= 0")
    if float(targeted.get("merge_gap", 0)) < 0:
        raise ValueError("targeted.merge_gap must be >= 0")
    if int(targeted.get("limit", 0)) < 0:
        raise ValueError("targeted.limit must be >= 0")
    if float(targeted.get("snap_max_shift", 0)) < 0:
        raise ValueError("targeted.snap_max_shift must be >= 0")
    if float(llm.get("min_clip", 0)) <= 0:
        raise ValueError("llm.min_clip must be > 0")
    if float(llm.get("max_clip", 0)) < float(llm.get("min_clip", 0)):
        raise ValueError("llm.max_clip must be >= llm.min_clip")
    if float(llm.get("timeout", 0)) <= 0:
        raise ValueError("llm.timeout must be > 0")
    if int(llm.get("max_tokens", 0)) <= 0:
        raise ValueError("llm.max_tokens must be > 0")
    for key in ("tag_membership", "peak_floor", "music_threshold"):
        value = float(config.get("yamnet", {}).get(key, 0))
        if not 0 <= value <= 1:
            raise ValueError(f"yamnet.{key} must be between 0 and 1")
    if float(whisper.get("log_prob_threshold", 0)) > 0:
        raise ValueError("whisper.log_prob_threshold must be <= 0")
    if int(whisper.get("seed", 0)) < 0:
        raise ValueError("whisper.seed must be >= 0")
    if float(config.get("outro", {}).get("tail_seconds", 0)) < 0:
        raise ValueError("outro.tail_seconds must be >= 0")


def load_config(path=None):
    config = deepcopy(DEFAULTS)
    path = Path(path) if path else CONFIG_PATH
    if path.is_file():
        _merge(config, _read_toml(path))
    _validate(config)
    return config


CONFIG = load_config()


def reload():
    global CONFIG
    CONFIG = load_config()
    return CONFIG


def _toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value: {value!r}")


def save_config(values):
    candidate = deepcopy(DEFAULTS)
    _merge(candidate, values)
    _validate(candidate)
    lines = [
        "# Clip configuration.",
        "# Edit in the Settings page or directly in this file.",
        "# CLI flags override these values.",
        "",
    ]
    for section, defaults in DEFAULTS.items():
        data = candidate.get(section, {})
        lines.append(f"[{section}]")
        for key in defaults:
            lines.append(f"{key} = {_toml_value(data.get(key, defaults[key]))}")
        lines.append("")
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)
    reload()
    return CONFIG


def reset_config():
    return save_config(DEFAULTS)


def get(section, key, default=None):
    return CONFIG.get(section, {}).get(key, default)


def section(name):
    return CONFIG.get(name, {})


def path(section_name, key):
    value = get(section_name, key)
    if value is None:
        return None
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--get")
    parser.add_argument("--path")
    args = parser.parse_args()
    config = load_config(args.path)
    if args.env:
        whisper = config["whisper"]
        values = {
            "WHISPER_MODEL": whisper["model"],
            "WHISPER_MODEL_REVISION": whisper["revision"],
            "WHISPER_LOG_PROB_THRESHOLD": whisper["log_prob_threshold"],
            "WHISPER_SEED": whisper["seed"],
            "WHISPER_LOCAL_FILES_ONLY": "1" if whisper["local_files_only"] else "0",
        }
        print("\n".join(f"export {k}={shlex.quote(str(v))}" for k, v in values.items()))
        return
    if args.get:
        section_name, _, key = args.get.partition(".")
        print(config.get(section_name, {}).get(key))
        return
    print(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()
