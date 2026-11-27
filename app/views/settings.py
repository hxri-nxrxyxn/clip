"""Settings view for configuring application parameters."""

import streamlit as st

from app import config
from app.settings_ui import SETTINGS_FIELDS, SETTINGS_SECTIONS, setting_widget


def render() -> None:
    st.title("Settings")
    st.caption("Edit the pipeline settings. Values are saved directly to the single config file.")
    notice = st.session_state.pop("settings_notice", None)
    if notice:
        st.success(notice)
    st.caption(f"Config file: {config.config_path()}")
    st.caption("Secrets such as the Qwen API key may be stored here.")
    if st.button("Reset config to defaults", icon=":material/restart_alt:"):
        config.reset_config()
        st.session_state["settings_notice"] = "Config reset to defaults."
        st.rerun()

    with st.form("settings_form"):
        values: dict[str, dict[str, object]] = {}
        for section, title, description in SETTINGS_SECTIONS:
            with st.expander(title, expanded=section in {"targeted", "llm"}):
                st.caption(description)
                fields = SETTINGS_FIELDS[section]
                for index in range(0, len(fields), 2):
                    columns = st.columns(2)
                    for column, field in zip(columns, fields[index : index + 2]):
                        key, label, kind, options = field
                        with column:
                            values.setdefault(section, {})[key] = setting_widget(
                                section,
                                key,
                                label,
                                kind,
                                options,
                                config.get(section, key),
                            )
        submitted = st.form_submit_button(
            "Save config",
            type="primary",
            icon=":material/save:",
        )
        if submitted:
            try:
                config.save_config(values)
                st.session_state["settings_notice"] = f"Saved config to {config.config_path()}."
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save config: {exc}")

    with st.expander("Effective config", expanded=False):
        st.json(config.CONFIG)
