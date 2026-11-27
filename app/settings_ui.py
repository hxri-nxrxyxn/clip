from typing import Any

import streamlit as st

SETTINGS_SECTIONS: list[tuple[str, str, str]] = [
    (
        "targeted",
        "Targeted transcription",
        "Window expansion, trigger filtering, and quiet-gap snapping.",
    ),
    (
        "llm",
        "Qwen selection",
        "Local endpoint, model, clip limits, and fallback behavior.",
    ),
    (
        "whisper",
        "Whisper",
        "Model, revision, decoding threshold, and determinism.",
    ),
    (
        "yamnet",
        "YAMNet",
        "Tag thresholds, trigger groups, scan window, and model paths.",
    ),
    (
        "merge_tags",
        "Tagged transcript",
        "Line splitting, cue timing, duplicate cleanup, and VTT wrapping.",
    ),
    (
        "outro",
        "Outro trim",
        "Speech-end confidence and tail padding.",
    ),
]

SETTINGS_FIELDS: dict[str, list[tuple[str, str, str, dict[str, Any]]]] = {
    "targeted": [
        ("pre", "Pre-roll seconds", "float", {"min_value": 0.0, "step": 1.0}),
        ("post", "Post-roll seconds", "float", {"min_value": 0.0, "step": 1.0}),
        ("merge_gap", "Merge gap seconds", "float", {"min_value": 0.0, "step": 1.0}),
        ("limit", "Candidate limit (0 = all)", "int", {"min_value": 0, "step": 1}),
        ("use_llm", "Use Qwen by default", "bool", {}),
        ("quiet_rel_db", "Quiet relative dB", "float", {"step": 0.5}),
        ("snap_max_shift", "Snap max shift seconds", "float", {"min_value": 0.0, "step": 0.5}),
        (
            "music_threshold",
            "Music tag threshold",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.05},
        ),
    ],
    "llm": [
        ("base_url", "Base URL", "text", {}),
        ("model", "Model name", "text", {}),
        ("timeout", "Timeout seconds", "float", {"min_value": 1.0, "step": 10.0}),
        ("disable_thinking", "Disable thinking", "bool", {}),
        ("max_tokens", "Max tokens", "int", {"min_value": 1, "step": 64}),
        ("min_clip", "Minimum clip seconds", "float", {"min_value": 0.1, "step": 0.5}),
        ("max_clip", "Maximum clip seconds", "float", {"min_value": 0.1, "step": 1.0}),
        ("heuristic_radius", "Fallback radius seconds", "float", {"min_value": 0.1, "step": 0.5}),
        ("api_key", "API key", "password", {}),
        ("api_key_file", "API key file", "text", {}),
        ("api_key_container", "API key container", "text", {}),
    ],
    "whisper": [
        ("model", "Model", "text", {}),
        ("revision", "Revision", "text", {}),
        ("log_prob_threshold", "Log-probability threshold", "float", {"step": 0.05}),
        ("seed", "Seed", "int", {"min_value": 0, "step": 1}),
        ("local_files_only", "Local files only", "bool", {}),
    ],
    "yamnet": [
        ("sample_rate", "Sample rate", "int", {"min_value": 8000, "step": 1000}),
        ("window", "Window samples", "int", {"min_value": 1000, "step": 1000}),
        ("hop", "Hop samples", "int", {"min_value": 100, "step": 100}),
        ("yamnet_samples", "YAMNet samples", "int", {"min_value": 1000, "step": 100}),
        (
            "tag_membership",
            "Tag membership",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.05},
        ),
        ("peak_floor", "Peak floor", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("loud_db", "Loud dB threshold", "float", {"step": 0.5}),
        (
            "music_threshold",
            "Music threshold",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.05},
        ),
        ("music_index", "Music class index", "int", {"min_value": 0, "step": 1}),
        ("trigger_groups", "Trigger groups", "list", {"help": "Comma-separated class groups"}),
        ("model", "Model path", "text", {}),
        ("class_map", "Class map path", "text", {}),
    ],
    "merge_tags": [
        ("membership", "Membership", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        ("peak_floor", "Peak floor", "float", {"min_value": 0.0, "max_value": 1.0, "step": 0.05}),
        (
            "abs_high",
            "High absolute score",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.05},
        ),
        (
            "abs_med",
            "Medium absolute score",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.05},
        ),
        (
            "abs_low",
            "Low absolute score",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.05},
        ),
        ("max_bridge", "Max bridge seconds", "float", {"min_value": 0.0, "step": 0.5}),
        ("chunk_seconds", "Percentile chunk seconds", "float", {"min_value": 1.0, "step": 10.0}),
        ("percentile_min_spans", "Percentile min spans", "int", {"min_value": 1, "step": 1}),
        ("loud_gap", "Loud gap seconds", "float", {"min_value": 0.0, "step": 0.5}),
        (
            "music_threshold",
            "Music threshold",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.05},
        ),
        ("music_gap", "Music gap seconds", "float", {"min_value": 0.0, "step": 0.5}),
        ("pause", "Line pause seconds", "float", {"min_value": 0.0, "step": 0.1}),
        ("max_words", "Max words per line", "int", {"min_value": 1, "step": 1}),
        ("max_line_seconds", "Max line seconds", "float", {"min_value": 0.1, "step": 0.5}),
        ("min_cue_seconds", "Min cue seconds", "float", {"min_value": 0.01, "step": 0.1}),
        ("max_cue_seconds", "Max cue seconds", "float", {"min_value": 0.1, "step": 0.5}),
        ("tag_attach_lead", "Tag attach lead", "float", {"min_value": 0.0, "step": 0.1}),
        ("vtt_wrap_columns", "VTT wrap columns", "int", {"min_value": 10, "step": 1}),
        ("max_repeat", "Max repeated words", "int", {"min_value": 1, "step": 1}),
        ("dup_window", "Duplicate window seconds", "float", {"min_value": 0.0, "step": 0.5}),
        (
            "dup_ratio",
            "Duplicate ratio",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.01},
        ),
        (
            "low_conf_p",
            "Low confidence probability",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.01},
        ),
        (
            "high_conf_p",
            "High confidence probability",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.01},
        ),
        ("isolation_window", "Isolation window seconds", "float", {"min_value": 0.0, "step": 0.1}),
        ("min_word_dur", "Min word duration", "float", {"min_value": 0.0, "step": 0.01}),
        ("max_word_dur", "Max word duration", "float", {"min_value": 0.0, "step": 0.1}),
    ],
    "outro": [
        ("tail_seconds", "Tail seconds", "float", {"min_value": 0.0, "step": 0.5}),
        (
            "confidence_threshold",
            "Confidence threshold",
            "float",
            {"min_value": 0.0, "max_value": 1.0, "step": 0.01},
        ),
    ],
}


def setting_widget(
    section: str,
    key: str,
    label: str,
    kind: str,
    options: dict[str, Any],
    value: Any,
) -> Any:
    widget_key = f"setting_{section}_{key}"
    help_text = options.get("help")
    if kind == "bool":
        return st.toggle(label, value=bool(value), key=widget_key, help=help_text)
    if kind in {"float", "int"}:
        kwargs = {
            name: options[name] for name in ("min_value", "max_value", "step") if name in options
        }
        if kind == "float":
            return float(
                st.number_input(
                    label,
                    value=float(value),
                    format="%.3f",
                    key=widget_key,
                    help=help_text,
                    **kwargs,
                )
            )
        return int(
            st.number_input(
                label,
                value=int(value),
                step=int(kwargs.get("step", 1)),
                min_value=kwargs.get("min_value"),
                max_value=kwargs.get("max_value"),
                key=widget_key,
                help=help_text,
            )
        )
    if kind == "list":
        raw = st.text_input(
            label,
            value=", ".join(str(item) for item in value or []),
            key=widget_key,
            help=help_text,
        )
        return [item.strip() for item in raw.split(",") if item.strip()]
    return st.text_input(
        label,
        value=str(value or ""),
        key=widget_key,
        help=help_text,
        type="password" if kind == "password" else "default",
    )
