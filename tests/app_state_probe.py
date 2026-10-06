"""Test helper: runs the app, then stores the current inputs as a .pallet document in session state.

AppTest can't drive file uploads or read download buttons, so tests use this to check that the
app's inputs map to and from .pallet documents without loss.
"""

import runpy
from pathlib import Path

import streamlit as st

runpy.run_path(str(Path(__file__).resolve().parents[1] / "app.py"))

from pallet_builder import inputs
from ui import state

st.session_state["_probe_document"] = inputs.dumps(state.state_to_document())
