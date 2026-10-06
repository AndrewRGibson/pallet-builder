"""Pallet Builder: Streamlit entry point. Run with ``uv run streamlit run app.py``.

The page is a title and one row of tabs. Inputs live on the Input tab (always drawn, so Streamlit keeps
their values); the heavier result tabs only compute while they're open.
"""

from __future__ import annotations

import streamlit as st

from pallet_builder import Pallet, __version__
from ui import inputs_tab, results, sensitivity, state, style, view3d
from ui.solving import limit_text, solve

TABS = ["Overview", "Input", "Summary", "3D view", "Placements", "By iteration", "Sensitivity"]
WEIGHT_UNIT_FOR = {"in": "lb", "cm": "kg"}

st.set_page_config(page_title="Pallet Builder", page_icon="\U0001F4E6", layout="wide")
style.apply()
state.init_state()

st.markdown(f"## \U0001F4E6 Pallet Builder <span style='font-size:0.8rem;opacity:0.6'>v{__version__}</span>",
            unsafe_allow_html=True)
# Lazy tabs: on_change="rerun" with a key reruns on tab switches and sets each tab's .open, so the
# heavier tabs below can skip work while closed. Opens on Summary; Overview explains the app.
overview_tab, input_tab, summary_tab, view_tab, table_tab, iterations_tab, sens_tab = st.tabs(
    TABS, key="main_tab", on_change="rerun", default="Summary")

with input_tab:
    strip = st.empty()
    inputs_tab.render_file_bar()
    st.divider()
    inputs_tab.render_inputs()

# Auto-solve uses the current inputs; otherwise the last inputs the Solve button committed.
ss = st.session_state
current = state.solve_inputs()
if ss.auto_solve or "solved_inputs" not in ss:
    ss.solved_inputs = current
pallet_args, case_args, ga_args, stacking, min_support = ss.solved_inputs
stale = ss.solved_inputs != current

try:
    pallet = Pallet(**pallet_args)
    with st.spinner("Solving…"):
        solved = solve(pallet_args, case_args, ga_args, stacking, min_support)
except ValueError as exc:
    inputs_tab.render_result_strip(strip, "", stale=stale, error=str(exc))
    with summary_tab:
        st.error(f"Invalid input: {exc}")
    st.stop()

result, count = solved.result, solved.count
length_unit = pallet.unit
weight_unit = WEIGHT_UNIT_FOR.get(length_unit, "lb")
if count:
    headline = f"<b>{count} cases</b> · {result.layers} layers × {result.cases_per_layer} per layer"
    if pallet.height is not None:
        headline += f" · cube use {result.volume_utilization:.0%}"
    reason = limit_text(solved, pallet)
    headline += f" · {reason}" if reason else ""
else:
    headline = "<b>No cases fit</b> · see the Summary tab for why"
inputs_tab.render_result_strip(strip, headline, stale=stale)

with overview_tab:
    results.render_overview()

with summary_tab:
    results.render_summary(pallet, solved, case_args, weight_unit)

if view_tab.open:
    with view_tab:
        if result.placements:
            view3d.render(pallet, result)
        else:
            st.info("Nothing to draw. Adjust the values on the Input tab.")

if table_tab.open:
    with table_tab:
        results.render_placements(result)

if iterations_tab.open:
    with iterations_tab:
        results.render_iterations(result)


def solve_variant(variant_case_args: dict) -> tuple:
    """(count, result) for a sensitivity variant, with the same pallet and solver settings."""
    variant = solve(pallet_args, variant_case_args, ga_args, stacking, min_support)
    return variant.count, variant.result


with sens_tab:
    # The tab's widgets are always drawn (so they keep their values); the solves only run while it's open.
    sensitivity.render_tab(solve_variant, case_args, (count, result), length_unit, pallet.max_weight,
                           compute=sens_tab.open)
