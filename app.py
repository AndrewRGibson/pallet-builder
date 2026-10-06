from __future__ import annotations

import json

import matplotlib.pyplot as plt
import streamlit as st
from matplotlib.patches import Patch, Rectangle

from pallet_builder import (
    STANDARD_PALLETS,
    Case,
    Pallet,
    convert_length,
    maximize_case_count,
    solve_pallet_layout,
)

APP_VERSION = "0.1.0"
LENGTH_UNITS = ["in", "mm", "cm", "m", "ft"]
WEIGHT_UNITS = {"lb": 0.45359237, "kg": 1.0}  # kilograms per unit
CUSTOM = "Custom"
MODE_MAX = "Max cases"
MODE_FIXED = "Fixed quantity"

st.set_page_config(page_title="Pallet Builder", page_icon="📦", layout="wide")
st.markdown(
    """
    <style>
        .block-container { padding-top: 2.75rem; padding-bottom: 0.5rem; }
        section[data-testid="stSidebar"] .block-container { padding-top: 0.6rem; }
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.35rem; }
        section[data-testid="stSidebar"] hr { margin: 0.4rem 0; }
        .section-label { font-size: 0.75rem; font-weight: 700; letter-spacing: 0.06em;
                         text-transform: uppercase; opacity: 0.65; margin: 0.2rem 0 0.25rem; }
        [data-testid="stMetricValue"] { font-size: 1.35rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Session state and unit-aware callbacks -------------------------------------------------

def _round(value: float) -> float:
    return round(value, 4)


def _apply_preset() -> None:
    name = st.session_state.preset
    if name == CUSTOM:
        return
    spec = STANDARD_PALLETS[name]
    unit = spec["unit"]
    st.session_state.update(
        p_unit=unit,
        _p_unit_prev=unit,
        p_len=float(spec["length"]),
        p_wid=float(spec["width"]),
        p_deck=float(spec["deck_height"]),
        w_unit=spec["weight_unit"],
        _w_unit_prev=spec["weight_unit"],
        p_maxw=float(spec["max_weight"]),
    )


def _mark_custom() -> None:
    st.session_state.preset = CUSTOM


def _convert_pallet_unit() -> None:
    old, new = st.session_state._p_unit_prev, st.session_state.p_unit
    for key in ("p_len", "p_wid", "p_deck", "p_height"):
        st.session_state[key] = _round(convert_length(st.session_state[key], old, new))
    factor = convert_length(1.0, old, new)
    st.session_state.p_maxvol = _round(st.session_state.p_maxvol * factor**3)
    st.session_state.p_maxarea = _round(st.session_state.p_maxarea * factor**2)
    st.session_state._p_unit_prev = new


def _convert_case_unit() -> None:
    old, new = st.session_state._c_unit_prev, st.session_state.c_unit
    for key in ("c_len", "c_wid", "c_hgt"):
        st.session_state[key] = _round(convert_length(st.session_state[key], old, new))
    st.session_state._c_unit_prev = new


def _convert_weight_unit() -> None:
    old, new = st.session_state._w_unit_prev, st.session_state.w_unit
    factor = WEIGHT_UNITS[old] / WEIGHT_UNITS[new]
    for key in ("p_maxw", "c_weight"):
        st.session_state[key] = _round(st.session_state[key] * factor)
    st.session_state._w_unit_prev = new


def _init_state() -> None:
    if "preset" in st.session_state:
        return
    st.session_state.update(
        preset="CHEP",
        p_height=0.0,
        p_maxvol=0.0,
        p_maxarea=0.0,
        c_len=12.0,
        c_wid=10.0,
        c_hgt=8.0,
        c_weight=20.0,
        c_unit="in",
        _c_unit_prev="in",
        c_tsu=True,
        mode=MODE_MAX,
        qty=20,
        opt=False,
        ga_gens=12,
        ga_pop=12,
        ga_seed=0,
    )
    _apply_preset()


def _preset_label(name: str) -> str:
    if name == CUSTOM:
        return CUSTOM
    spec = STANDARD_PALLETS[name]
    return f"{name} · {spec['length']:g}×{spec['width']:g} {spec['unit']}"


def _section(label: str) -> None:
    st.markdown(f"<div class='section-label'>{label}</div>", unsafe_allow_html=True)


def _num(label: str, key: str, *, on_change=None, help: str | None = None, min_value: float = 0.0) -> float:
    return st.number_input(label, key=key, min_value=min_value, step=1.0, format="%g", on_change=on_change, help=help)


# --- Solving --------------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=64)
def _solve(pallet_args: dict, case_args: dict, mode: str, qty: int, opt: dict | None):
    pallet = Pallet(**pallet_args)
    case = Case(**case_args)
    if mode == MODE_MAX:
        count, result = maximize_case_count(pallet, case)
        # Re-solve one more case to explain what stops the count going higher.
        limit = solve_pallet_layout(pallet, [Case(**{**case_args, "quantity": count + 1})]).violations if count else []
        return count, result, limit
    case_args = {**case_args, "quantity": qty}
    if opt:
        result = solve_pallet_layout(
            pallet,
            [Case(**case_args)],
            optimize=True,
            optimization_generations=opt["gens"],
            optimization_population=opt["pop"],
            optimization_seed=opt["seed"],
        )
    else:
        result = solve_pallet_layout(pallet, [Case(**case_args)])
    return len(result.placements), result, []


def _summarize_violations(violations: list[str]) -> list[str]:
    """Collapse the per-case "no footprint" messages into one line."""
    no_room = [v for v in violations if v.startswith("No feasible footprint")]
    summary = [v for v in violations if v not in no_room]
    if no_room:
        summary.append(f"{len(no_room)} case(s) had no room left on the deck.")
    return summary


def _limit_reason(violations: list[str]) -> str:
    text = " ".join(violations).lower()
    if "weight" in text:
        return "max weight"
    if "volume" in text:
        return "max volume"
    if "plan area" in text:
        return "max plan area"
    if "height" in text:
        return "max load height"
    return "deck footprint"


# --- Rendering ------------------------------------------------------------------------------

def _render_plan(pallet: Pallet, result) -> None:
    # Size the figure so the plan's longest side is ~3in: it fits on screen beside the summary.
    scale = 3.0 / max(pallet.length, pallet.width)
    fig, ax = plt.subplots(figsize=(pallet.length * scale + 0.9, pallet.width * scale + 1.0), dpi=100)
    ax.add_patch(Rectangle((0, 0), pallet.length, pallet.width, facecolor="#f1f5f9", edgecolor="#0f172a", linewidth=2))

    base_color, rotated_color = "#93c5fd", "#fcd34d"
    label_cases = len(result.placements) <= 80
    for index, placement in enumerate(result.placements, start=1):
        rotated = placement.orientation[:2] != (0, 1)
        ax.add_patch(
            Rectangle(
                (placement.x, placement.y),
                placement.length,
                placement.width,
                facecolor=rotated_color if rotated else base_color,
                edgecolor="#1e3a8a",
                linewidth=0.8,
            )
        )
        if label_cases:
            ax.text(placement.x + placement.length / 2, placement.y + placement.width / 2, str(index),
                    ha="center", va="center", fontsize=7, color="#0f172a")

    pad = max(pallet.length, pallet.width) * 0.03
    ax.set_xlim(-pad, pallet.length + pad)
    ax.set_ylim(-pad, pallet.width + pad)
    ax.set_aspect("equal")
    ax.set_xlabel(f"Length ({pallet.unit})", fontsize=8)
    ax.set_ylabel(f"Width ({pallet.unit})", fontsize=8)
    ax.tick_params(labelsize=7)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.legend(
        handles=[Patch(color=base_color, label="As entered"), Patch(color=rotated_color, label="Rotated")],
        loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2, fontsize=7, frameon=False,
    )
    fig.tight_layout()
    st.pyplot(fig, width="content")
    plt.close(fig)


def _placement_rows(result) -> list[dict]:
    return [
        {
            "#": index,
            "x": round(p.x, 3),
            "y": round(p.y, 3),
            "z": round(p.z, 3),
            "length": round(p.length, 3),
            "width": round(p.width, 3),
            "height": round(p.height, 3),
            "rotated": p.orientation[:2] != (0, 1),
            "tipped": p.orientation[2] != 2,
        }
        for index, p in enumerate(result.placements, start=1)
    ]


# --- Sidebar: every input that controls the solve ------------------------------------------

_init_state()

with st.sidebar:
    st.markdown(f"### 📦 Pallet Builder <span style='font-size:0.7rem;opacity:0.6'>v{APP_VERSION}</span>",
                unsafe_allow_html=True)

    _section("Pallet")
    st.selectbox("Preset", [*sorted(STANDARD_PALLETS), CUSTOM], key="preset", format_func=_preset_label,
                 on_change=_apply_preset)
    c1, c2 = st.columns(2)
    c1.selectbox("Length unit", LENGTH_UNITS, key="p_unit", on_change=_convert_pallet_unit)
    c2.selectbox("Weight unit", list(WEIGHT_UNITS), key="w_unit", on_change=_convert_weight_unit,
                 help="Applies to pallet max weight and case weight.")
    c1, c2 = st.columns(2)
    with c1:
        _num("Length", "p_len", on_change=_mark_custom, min_value=0.001)
    with c2:
        _num("Width", "p_wid", on_change=_mark_custom, min_value=0.001)
    c1, c2 = st.columns(2)
    with c1:
        _num("Max load height", "p_height", help="Height of the load above the deck. 0 = no limit.")
    with c2:
        _num("Max weight", "p_maxw", on_change=_mark_custom, help="Total case weight. 0 = no limit.")
    with st.expander("More limits", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            _num(f"Max volume ({st.session_state.p_unit}³)", "p_maxvol", help="0 = no limit.")
        with c2:
            _num(f"Max plan area ({st.session_state.p_unit}²)", "p_maxarea", help="0 = no limit.")
        _num("Deck height", "p_deck", on_change=_mark_custom, min_value=0.001,
             help="Pallet's own height. Shown for reference; it does not limit the load.")

    st.divider()
    _section("Case")
    c1, c2, c3 = st.columns(3)
    with c1:
        _num("Length", "c_len", min_value=0.001)
    with c2:
        _num("Width", "c_wid", min_value=0.001)
    with c3:
        _num("Height", "c_hgt", min_value=0.001)
    c1, c2 = st.columns(2)
    with c1:
        _num(f"Weight ({st.session_state.w_unit})", "c_weight")
    c2.selectbox("Unit", LENGTH_UNITS, key="c_unit", on_change=_convert_case_unit)
    st.toggle("This side up", key="c_tsu", help="Off lets the solver tip cases onto a side or end.")

    st.divider()
    _section("Solve")
    st.segmented_control("Mode", [MODE_MAX, MODE_FIXED], key="mode", label_visibility="collapsed")
    if st.session_state.mode == MODE_FIXED:
        c1, c2 = st.columns([1, 1.2])
        with c1:
            st.number_input("Quantity", key="qty", min_value=1, step=1)
        with c2:
            st.toggle("GA optimizer", key="opt", help="Search alternative placement orders when the greedy packer can't fit them all.")
        if st.session_state.opt:
            c1, c2, c3 = st.columns(3)
            c1.number_input("Generations", key="ga_gens", min_value=1, step=1)
            c2.number_input("Population", key="ga_pop", min_value=2, step=1)
            c3.number_input("Seed", key="ga_seed", min_value=0, step=1)
    else:
        st.caption("Finds the most cases that fit one layer. The GA optimizer is available in fixed-quantity mode.")

ss = st.session_state
mode = ss.mode or MODE_MAX
pallet_args = {
    "length": ss.p_len,
    "width": ss.p_wid,
    "height": ss.p_height or None,
    "unit": ss.p_unit,
    "max_weight": ss.p_maxw or None,
    "max_volume": ss.p_maxvol or None,
    "max_plan_area": ss.p_maxarea or None,
    "deck_height": ss.p_deck,
    "name": None if ss.preset == CUSTOM else ss.preset,
}
case_args = {
    "name": "Case",
    "length": ss.c_len,
    "width": ss.c_wid,
    "height": ss.c_hgt,
    "weight": ss.c_weight,
    "unit": ss.c_unit,
    "this_side_up": ss.c_tsu,
}
opt_args = {"gens": ss.ga_gens, "pop": ss.ga_pop, "seed": ss.ga_seed} if mode == MODE_FIXED and ss.opt else None

# --- Main area: results ---------------------------------------------------------------------

try:
    pallet = Pallet(**pallet_args)
    with st.spinner("Solving…"):
        count, result, limit_violations = _solve(pallet_args, case_args, mode, ss.qty, opt_args)
except ValueError as exc:
    st.error(f"Invalid input: {exc}")
    st.stop()

w_unit = ss.w_unit
placed_weight = count * ss.c_weight
load_height = max((p.z + p.height for p in result.placements), default=0.0)
empty_area = pallet.plan_area * (1 - result.utilization)

if mode == MODE_MAX:
    ok = count > 0
    headline = f"{count} cases fit" if ok else "No cases fit"
else:
    ok = result.feasible
    headline = f"All {ss.qty} cases fit" if ok else f"{count} of {ss.qty} cases placed"

pallet_name = pallet.name or "Custom pallet"
st.markdown(f"#### {headline}")
st.caption(
    f"{pallet_name} · {pallet.length:g}×{pallet.width:g} {pallet.unit} deck · "
    f"case {ss.c_len:g}×{ss.c_wid:g}×{ss.c_hgt:g} {ss.c_unit} · {mode.lower()}"
)

plan_col, info_col = st.columns([1.4, 1], gap="large")
with plan_col:
    if result.placements:
        _render_plan(pallet, result)
    else:
        st.info("Nothing to draw. Adjust the inputs in the sidebar.")

with info_col:
    m1, m2 = st.columns(2)
    m1.metric("Status", "Feasible" if ok else "Infeasible")
    m2.metric("Cases", count)
    m1.metric("Deck coverage", f"{result.utilization:.1%}", help="Share of the deck footprint covered by cases.")
    m2.metric(
        "Load weight",
        f"{placed_weight:,.1f} {w_unit}",
        help=f"Limit: {pallet.max_weight:,.1f} {w_unit}" if pallet.max_weight else "No weight limit",
    )
    m1.metric(
        "Load height",
        f"{load_height:g} {pallet.unit}",
        help=f"Limit: {pallet.height:g} {pallet.unit}" if pallet.height else "No height limit",
    )
    m2.metric("Empty deck", f"{empty_area:,.0f} {pallet.unit}²")

    if mode == MODE_MAX and ok and limit_violations:
        st.info(f"Limited by **{_limit_reason(limit_violations)}**: one more case would break it.")
    if result.violations and not (mode == MODE_MAX and ok):
        st.error("\n".join(f"- {v}" for v in _summarize_violations(result.violations)))

    rotated = sum(1 for p in result.placements if p.orientation[:2] != (0, 1))
    tipped = sum(1 for p in result.placements if p.orientation[2] != 2)
    st.caption(
        f"{count - rotated} as entered · {rotated} rotated · {tipped} tipped · "
        f"deck height {pallet.deck_height:g} {pallet.unit} (not counted in load height)"
    )

table_tab, export_tab = st.tabs(["Placements", "Export"])
with table_tab:
    st.dataframe(_placement_rows(result), hide_index=True, width="stretch", height=300)
with export_tab:
    payload = {
        "pallet": pallet_args,
        "case": case_args,
        "weight_unit": w_unit,
        "mode": mode,
        "quantity": ss.qty if mode == MODE_FIXED else None,
        "optimizer": opt_args,
        "result": {
            "cases": count,
            "feasible": ok,
            "deck_coverage": result.utilization,
            "placed_weight": placed_weight,
            "violations": result.violations,
            "placements": _placement_rows(result),
        },
    }
    st.download_button(
        "Download layout (JSON)",
        json.dumps(payload, indent=2),
        file_name="pallet_layout.json",
        mime="application/json",
    )
    st.caption("Includes every input, so a run can be reproduced or reviewed later.")
