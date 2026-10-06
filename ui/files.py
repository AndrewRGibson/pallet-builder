"""The file bar on the Input tab: load a sample, open a .pallet file, save, or reset to defaults."""

from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from pallet_builder import inputs as input_files
from ui import state

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"


@st.cache_data(show_spinner=False)
def samples() -> dict[str, dict]:
    """Sample documents shipped with the app, keyed by their display name (always available)."""
    return {doc["name"]: doc for doc in (input_files.load(path) for path in input_files.sample_paths(SAMPLES_DIR))}


def _load_sample() -> None:
    doc = samples()[st.session_state.sample_choice]
    state.document_to_state(doc)
    st.session_state.file_message = ("success", f"Loaded sample “{doc['name']}”.")


def _upload_key() -> str:
    return f"upload_{st.session_state.upload_nonce}"


def _load_upload() -> None:
    upload = st.session_state.get(_upload_key())
    if upload is None:
        return
    try:
        doc = input_files.loads(upload.getvalue().decode("utf-8"))
    except (UnicodeDecodeError, input_files.InputFileError) as exc:
        st.session_state.file_message = ("error", f"Couldn't load {upload.name}: {exc}")
        return
    state.document_to_state(doc)
    st.session_state.file_message = ("success", f"Loaded {upload.name}.")
    # A fresh uploader, so loading the same file again (after edits) works.
    st.session_state.upload_nonce += 1


def default_file_name() -> str:
    """A descriptive name from the current inputs, used when the Name field is blank."""
    ss = st.session_state
    length_unit, _ = state.units()
    pallet = ss.preset if ss.preset != state.CUSTOM else f"{ss.p_len:g}x{ss.p_wid:g}"
    return f"{pallet} {ss.c_len:g}x{ss.c_wid:g}x{ss.c_hgt:g} {length_unit}"


def file_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "pallet-inputs"


def render() -> None:
    sample_col, open_col, save_col = st.columns(3, gap="large")
    with sample_col:
        st.selectbox("Sample", list(samples()), key="sample_choice",
                     help="Worked examples that ship with the app (also used as regression tests).")
        load_col, reset_col = st.columns(2)
        load_col.button("Load sample", on_click=_load_sample, width="stretch", icon=":material/download:")
        reset_col.button("Reset to defaults", on_click=state.reset_to_defaults, width="stretch",
                         icon=":material/restart_alt:")
        st.caption(samples()[st.session_state.sample_choice]["description"])
    with open_col:
        st.file_uploader(f"Open a {input_files.FILE_EXTENSION} file", type=[input_files.FILE_EXTENSION.lstrip(".")],
                         key=_upload_key(), on_change=_load_upload,
                         help="Pallet Builder input files (JSON with a .pallet extension).")
    with save_col:
        st.text_input("Name", key="file_name", placeholder=default_file_name(),
                      help="Saved inside the file and used for its file name. Blank uses the name shown.")
        doc = state.state_to_document()
        doc["name"] = doc["name"] or default_file_name()
        try:
            data = input_files.dumps(doc)
        except input_files.InputFileError as exc:
            st.button("Save .pallet", disabled=True, width="stretch", icon=":material/save:")
            st.caption(f"Can't save yet: {exc}")
        else:
            st.download_button("Save .pallet", data, file_name=file_slug(doc["name"]) + input_files.FILE_EXTENSION,
                               mime="application/json", width="stretch", icon=":material/save:")
    message = st.session_state.pop("file_message", None)
    if message:
        (st.success if message[0] == "success" else st.error)(message[1])
