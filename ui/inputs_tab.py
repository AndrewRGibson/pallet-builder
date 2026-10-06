"""The Input tab: result strip, file bar, and every input that controls the solve."""

from __future__ import annotations

import streamlit as st

from pallet_builder import STANDARD_PALLETS
from ui import files, state
from ui.state import CUSTOM, GA_STOP_FIXED, GA_STOP_STALL, STACKING_LABELS, UNIT_SYSTEMS


def _section(label: str) -> None:
    st.markdown(f"<div class='section-label'>{label}</div>", unsafe_allow_html=True)


def _num(label: str, key: str, *, on_change=None, help: str | None = None, min_value: float = 0.0) -> float:
    return st.number_input(label, key=key, min_value=min_value, step=1.0, format="%g", on_change=on_change, help=help)


def _limit(label: str, key: str, *, on_change=None, help: str | None = None) -> float | None:
    """An optional limit: blank means no limit, while 0 is a real (if strict) limit."""
    return st.number_input(label, key=key, min_value=0.0, value=None, step=1.0, format="%g",
                           placeholder="No limit", on_change=on_change, help=help)


def _solve_now() -> None:
    st.session_state.solved_inputs = state.solve_inputs()


def render_inputs() -> None:
    """Every input widget. Always drawn (even when the tab isn't open) so Streamlit keeps their values."""
    with st.container(key="inputs"):
        units_col, build_col, solve_col = st.columns(3, gap="large")
        with units_col:
            _section("Units")
            st.selectbox("System", list(UNIT_SYSTEMS), key="units", on_change=state.convert_units,
                         help="Applies to every length and weight. Switching converts the values already entered.")
            length_unit, weight_unit = state.units()

            st.divider()
            _section("Pallet")
            st.selectbox("Preset", [*sorted(STANDARD_PALLETS), CUSTOM], key="preset", format_func=state.preset_label,
                         on_change=state.apply_preset)
            _num(f"Length ({length_unit})", "p_len", on_change=state.mark_custom, min_value=0.001)
            _num(f"Width ({length_unit})", "p_wid", on_change=state.mark_custom, min_value=0.001)
            _num(f"Deck height ({length_unit})", "p_deck", on_change=state.mark_custom, min_value=0.001,
                 help="The pallet's own height; counts toward the max build height.")
            _limit(f"Max weight ({weight_unit})", "p_maxw", on_change=state.mark_custom,
                   help="Total case weight the pallet is rated for. Blank = no limit.")

        with build_col:
            _section("Build")
            _limit(f"Max build height ({length_unit})", "p_height",
                   help="Floor to top of load, including the pallet. Sets how many layers stack. "
                        "Blank = no limit (a single layer).")
            _limit(f"Max volume ({length_unit}³)", "p_maxvol", help="Total case volume. Blank = no limit.")
            _limit(f"Max plan area ({length_unit}²)", "p_maxarea", help="Combined case footprint. Blank = no limit.")

            st.divider()
            _section("Case")
            _num(f"Length ({length_unit})", "c_len", min_value=0.001)
            _num(f"Width ({length_unit})", "c_wid", min_value=0.001)
            _num(f"Height ({length_unit})", "c_hgt", min_value=0.001)
            _num(f"Weight ({weight_unit})", "c_weight")
            st.toggle("This side up", key="c_tsu",
                      help="Off lets the solver lay cases on a side or end. Every case in the load uses the same "
                           "upright side, so each layer top stays flat.")

        with solve_col:
            _section("Solve")
            auto_col, button_col = st.columns(2)
            auto_col.toggle("Auto-solve", key="auto_solve",
                            help="Re-solve whenever an input changes. Turn off for heavy settings (large GA runs) "
                                 "and press Solve when ready.")
            button_col.button("Solve", on_click=_solve_now, disabled=st.session_state.auto_solve, width="stretch",
                              icon=":material/play_arrow:")
            st.selectbox("Stacking", list(STACKING_LABELS), key="stacking", format_func=STACKING_LABELS.get,
                         help="Interlock flips every other layer (mirror or 180° turn) when that makes cases "
                              "bridge the seams below, without costing a case. 'No column stacking' requires interlock "
                              "and may trade cases for it; if no pattern interlocks, the load is limited to one layer.")
            # Inputs that don't apply are disabled rather than hidden: Streamlit drops the stored value of a
            # widget that isn't drawn, which would silently reset it to its minimum when shown again.
            st.number_input("Min support (%)", key="min_support", min_value=0.0, max_value=100.0, step=5.0,
                            format="%g", disabled=st.session_state.stacking == "column",
                            help="Each case must have at least this share of its base resting on cases below.")
            st.toggle("GA layer search", key="ga_on",
                      help="Genetic algorithm that targets the bound (deck area ÷ case footprint) per layer and "
                           "penalizes cases that don't fit. Runs where the block packer falls short.")
            ga_off = not st.session_state.ga_on
            stall_mode = st.session_state.ga_stop == GA_STOP_STALL
            st.selectbox("Stop rule", [GA_STOP_FIXED, GA_STOP_STALL], key="ga_stop", disabled=ga_off,
                         help="Fixed: run exactly the set number of generations. No improvement: stop once the best "
                              "result hasn't improved for the set number of generations (Generations is then the "
                              "limit).")
            st.number_input("Max generations" if stall_mode else "Generations", key="ga_gens", min_value=1,
                            max_value=2000, step=1, disabled=ga_off)
            st.number_input("Stop after no improvement for", key="ga_stall", min_value=1, max_value=500, step=1,
                            disabled=ga_off or not stall_mode, help="Generations without a better result before stopping.")
            st.number_input("Population", key="ga_pop", min_value=4, max_value=200, step=1, disabled=ga_off)
            st.number_input("Seed", key="ga_seed", min_value=0, step=1, disabled=ga_off)


def render_file_bar() -> None:
    files.render()


def render_result(placeholder, render_metrics, *, stale: bool, error: str | None = None) -> None:
    """The Result section at the bottom of the Input tab: every calculated metric, so an edit shows its full
    effect without switching tabs. ``render_metrics()`` draws the metric grid (shared with Summary)."""
    with placeholder.container():
        _section("Result")
        if error:
            st.error(f"Invalid input: {error}")
            return
        if stale:
            st.warning("Inputs have changed since this solve: press **Solve** to update.", icon=":material/sync:")
        render_metrics()
