from __future__ import annotations

import json

import matplotlib.pyplot as plt
import plotly.graph_objects as go
import streamlit as st
from matplotlib.patches import Patch, Rectangle

from pallet_builder import (
    STANDARD_PALLETS,
    Case,
    Pallet,
    __version__,
    convert_length,
    maximize_case_count,
    solve_pallet_layout,
)

APP_VERSION = __version__
# One unit system applies to every length and weight in the app.
UNIT_SYSTEMS = {"US (in, lb)": ("in", "lb"), "Metric (cm, kg)": ("cm", "kg")}
WEIGHT_UNITS = {"lb": 0.45359237, "kg": 1.0}  # kilograms per unit
# Typical max build heights (floor to top of load, including the pallet) applied with a preset.
DEFAULT_BUILD_HEIGHT = {"in": 60.0, "cm": 180.0}
_LENGTH_KEYS = ("p_len", "p_wid", "p_deck", "p_height", "c_len", "c_wid", "c_hgt")
_WEIGHT_KEYS = ("p_maxw", "c_weight")
CUSTOM = "Custom"
# Above this many cases the 3D view draws each layer as one block to stay responsive.
MAX_3D_CASES = 6000

st.set_page_config(page_title="Pallet Builder", page_icon="📦", layout="wide")
st.markdown(
    """
    <style>
        .block-container { padding-top: 2.75rem; padding-bottom: 0.5rem; }
        section[data-testid="stSidebar"] .block-container { padding-top: 0.6rem; }
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.35rem; }
        section[data-testid="stSidebar"] hr { margin: 0.4rem 0; }
        section[data-testid="stSidebar"] { min-width: 330px; }
        /* Sidebar properties: label and value on one line. */
        section[data-testid="stSidebar"] [data-testid="stNumberInput"],
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] {
            display: flex; flex-direction: row; align-items: center; gap: 0.5rem;
        }
        section[data-testid="stSidebar"] [data-testid="stNumberInput"] > [data-testid="stWidgetLabel"],
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] > [data-testid="stWidgetLabel"] {
            flex: 0 0 52%; min-height: 0; margin: 0; padding: 0;
        }
        section[data-testid="stSidebar"] [data-testid="stNumberInput"] > div,
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] > div {
            flex: 1 1 0; min-width: 0;
        }
        /* The +/- steppers crowd a half-width field; arrow keys still step the value. */
        section[data-testid="stSidebar"] [data-testid="stNumberInputStepUp"],
        section[data-testid="stSidebar"] [data-testid="stNumberInputStepDown"] { display: none; }
        .section-label { font-size: 0.75rem; font-weight: 700; letter-spacing: 0.06em;
                         text-transform: uppercase; opacity: 0.65; margin: 0.2rem 0 0.25rem; }
        [data-testid="stMetricValue"] { font-size: 1.35rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Session state and unit-aware callbacks -------------------------------------------------

def _round(value: float) -> float:
    return round(value, 6)


def _units() -> tuple[str, str]:
    """The active (length unit, weight unit)."""
    return UNIT_SYSTEMS.get(st.session_state.get("units"), ("in", "lb"))


def _apply_preset() -> None:
    name = st.session_state.preset
    spec = STANDARD_PALLETS.get(name)
    if name == CUSTOM or spec is None:
        return
    length_unit, weight_unit = _units()

    def length(key: str) -> float:
        return _round(convert_length(float(spec[key]), spec["unit"], length_unit))

    st.session_state.update(
        p_len=length("length"),
        p_wid=length("width"),
        p_deck=length("deck_height"),
        p_height=DEFAULT_BUILD_HEIGHT[length_unit],
        p_maxw=_round(float(spec["max_weight"]) * WEIGHT_UNITS[spec["weight_unit"]] / WEIGHT_UNITS[weight_unit]),
    )


def _mark_custom() -> None:
    st.session_state.preset = CUSTOM


def _convert_units() -> None:
    """Re-express every entered length and weight in the newly selected unit system."""
    old_length, old_weight = UNIT_SYSTEMS[st.session_state._units_prev]
    new_length, new_weight = _units()
    for key in _LENGTH_KEYS:
        st.session_state[key] = _round(convert_length(st.session_state[key], old_length, new_length))
    factor = convert_length(1.0, old_length, new_length)
    st.session_state.p_maxvol = _round(st.session_state.p_maxvol * factor**3)
    st.session_state.p_maxarea = _round(st.session_state.p_maxarea * factor**2)
    for key in _WEIGHT_KEYS:
        st.session_state[key] = _round(st.session_state[key] * WEIGHT_UNITS[old_weight] / WEIGHT_UNITS[new_weight])
    st.session_state._units_prev = st.session_state.units


def _init_state() -> None:
    if "preset" in st.session_state:
        return
    us = next(iter(UNIT_SYSTEMS))
    st.session_state.update(
        units=us,
        _units_prev=us,
        preset="CHEP",
        p_len=40.0,
        p_wid=48.0,
        p_deck=6.0,
        p_height=DEFAULT_BUILD_HEIGHT["in"],
        p_maxw=2200.0,
        p_maxvol=0.0,
        p_maxarea=0.0,
        c_len=12.0,
        c_wid=10.0,
        c_hgt=8.0,
        c_weight=20.0,
        c_tsu=True,
        ga_on=True,
        ga_gens=40,
        ga_pop=24,
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
def _solve(pallet_args: dict, case_args: dict, ga: tuple[int, int, int] | None):
    pallet = Pallet(**pallet_args)
    case = Case(**case_args)
    options = {"optimize": ga is not None}
    if ga is not None:
        options.update(optimization_generations=ga[0], optimization_population=ga[1], optimization_seed=ga[2])
    count, result = maximize_case_count(pallet, case, **options)
    # Re-solve one more case to explain what stops the count going higher.
    limit = (
        solve_pallet_layout(pallet, [Case(**{**case_args, "quantity": count + 1})], **options).violations
        if count else []
    )
    return count, result, limit


def _summarize_violations(violations: list[str]) -> list[str]:
    """Collapse the per-case "no footprint" messages into one line."""
    no_room = [v for v in violations if v.startswith("No feasible footprint")]
    summary = [v for v in violations if v not in no_room]
    if no_room:
        summary.append(f"{len(no_room)} case(s) had no room left on the pallet.")
    return summary


def _limit_reason(violations: list[str]) -> str:
    text = " ".join(violations).lower()
    if "weight" in text:
        return "max weight"
    if "volume" in text:
        return "max volume"
    if "plan area" in text:
        return "max plan area"
    return "pallet space"


# --- Rendering ------------------------------------------------------------------------------

_BOX_FACES = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
              (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
_BOX_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]


def _corners(x, y, z, length, width, height):
    return [
        (x, y, z), (x + length, y, z), (x + length, y + width, z), (x, y + width, z),
        (x, y, z + height), (x + length, y, z + height), (x + length, y + width, z + height), (x, y + width, z + height),
    ]


def _box_mesh(boxes: list[tuple], colors: list[str], **kwargs) -> go.Mesh3d:
    """All boxes as one mesh trace (one trace per box would make large loads sluggish)."""
    xs, ys, zs, i, j, k, face_colors = [], [], [], [], [], [], []
    for n, (box, color) in enumerate(zip(boxes, colors)):
        for cx, cy, cz in _corners(*box):
            xs.append(cx)
            ys.append(cy)
            zs.append(cz)
        for a, b, c in _BOX_FACES:
            i.append(8 * n + a)
            j.append(8 * n + b)
            k.append(8 * n + c)
            face_colors.append(color)
    return go.Mesh3d(x=xs, y=ys, z=zs, i=i, j=j, k=k, facecolor=face_colors, flatshading=True,
                     hoverinfo="skip", lighting={"ambient": 0.75, "diffuse": 0.6, "specular": 0.05}, **kwargs)


def _box_edges(boxes: list[tuple], color: str, width: float = 1.5, dash: str | None = None) -> go.Scatter3d:
    xs, ys, zs = [], [], []
    for box in boxes:
        corners = _corners(*box)
        for a, b in _BOX_EDGES:
            for point in (corners[a], corners[b], (None, None, None)):
                xs.append(point[0])
                ys.append(point[1])
                zs.append(point[2])
    return go.Scatter3d(x=xs, y=ys, z=zs, mode="lines", hoverinfo="skip",
                        line={"color": color, "width": width, "dash": dash})


def _render_3d(pallet: Pallet, result) -> None:
    deck = pallet.deck_height or 0.0
    layer_index = {z: n for n, z in enumerate(sorted({p.z for p in result.placements}))}
    shades = ["#3b82f6", "#93c5fd"]  # alternate layers so the stack reads clearly

    if len(result.placements) <= MAX_3D_CASES:
        boxes = [(p.x, p.y, p.z + deck, p.length, p.width, p.height) for p in result.placements]
        colors = [shades[layer_index[p.z] % 2] for p in result.placements]
        draw_edges = True
    else:
        # One block per layer: the bounding box of that layer's cases.
        boxes, colors = [], []
        for z, n in layer_index.items():
            layer = [p for p in result.placements if p.z == z]
            x0, y0 = min(p.x for p in layer), min(p.y for p in layer)
            x1, y1 = max(p.x + p.length for p in layer), max(p.y + p.width for p in layer)
            boxes.append((x0, y0, z + deck, x1 - x0, y1 - y0, layer[0].height))
            colors.append(shades[n % 2])
        draw_edges = True
        st.caption(f"{len(result.placements):,} cases: each layer is drawn as a single block.")

    traces = []
    if deck:
        deck_box = [(0.0, 0.0, 0.0, pallet.length, pallet.width, deck)]
        traces += [_box_mesh(deck_box, ["#b45309"]), _box_edges(deck_box, "#78350f", 2)]
    traces.append(_box_mesh(boxes, colors))
    if draw_edges:
        traces.append(_box_edges(boxes, "#1e3a8a", 1.2))
    if pallet.height:
        envelope = [(0.0, 0.0, 0.0, pallet.length, pallet.width, pallet.height)]
        traces.append(_box_edges(envelope, "#ef4444", 2, dash="dash"))

    def camera(eye_x, eye_y, eye_z, up_y=0.0, up_z=1.0):
        return {"scene.camera": {"eye": {"x": eye_x, "y": eye_y, "z": eye_z}, "up": {"x": 0, "y": up_y, "z": up_z}}}

    views = [("Iso", camera(1.5, -1.5, 1.1)), ("Front", camera(0, -2.3, 0.2)),
             ("Side", camera(2.3, 0, 0.2)), ("Top", camera(0, 0, 2.6, up_y=1.0, up_z=0.0))]
    fig = go.Figure(traces)
    unit = pallet.unit
    fig.update_layout(
        height=470,
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
        showlegend=False,
        scene={
            "aspectmode": "data",
            "xaxis": {"title": f"Length ({unit})"},
            "yaxis": {"title": f"Width ({unit})"},
            "zaxis": {"title": f"Height ({unit})"},
            "camera": views[0][1]["scene.camera"],
            "dragmode": "turntable",  # spin about the vertical axis so the pallet stays upright
        },
        updatemenus=[{
            "type": "buttons", "direction": "right", "x": 0, "y": 1.07, "xanchor": "left",
            "showactive": False, "pad": {"r": 4},
            "buttons": [{"label": label, "method": "relayout", "args": [args]} for label, args in views],
        }],
    )
    st.plotly_chart(fig, width="stretch", config={
        "displaylogo": False,
        "scrollZoom": True,
        "modeBarButtonsToRemove": ["orbitRotation", "pan3d"],
    })
    st.caption("Drag to spin · scroll to zoom · buttons reset the viewpoint. "
               "Brown = pallet deck, red dashes = max build height.")


def _render_plan(pallet: Pallet, placements) -> None:
    # Size the figure so the plan's longest side is ~3in: it fits on screen beside the summary.
    scale = 3.0 / max(pallet.length, pallet.width)
    fig, ax = plt.subplots(figsize=(pallet.length * scale + 0.9, pallet.width * scale + 1.0), dpi=100)
    ax.add_patch(Rectangle((0, 0), pallet.length, pallet.width, facecolor="#f1f5f9", edgecolor="#0f172a", linewidth=2))

    base_color, rotated_color = "#93c5fd", "#fcd34d"
    label_cases = len(placements) <= 80
    for index, placement in enumerate(placements, start=1):
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


def _render_solver_status(result) -> None:
    runs = result.solver_runs
    if not runs:
        return
    st.markdown("**Solver status**")
    st.dataframe(
        [
            {
                "Solver": run.solver,
                "Layers": run.family,
                "Per layer": run.cases_per_layer if run.ran else None,
                "Bound": run.target,
                "Used": "\u2714" if run.selected else "",
                "Note": run.note,
            }
            for run in runs
        ],
        hide_index=True,
        width="stretch",
    )

    ga_runs = [run for run in runs if run.history]
    if not ga_runs:
        return
    fig = go.Figure()
    for run in ga_runs:
        generations = [entry[0] for entry in run.history]
        suffix = f" ({run.family})" if len(ga_runs) > 1 else ""
        fig.add_scatter(x=generations, y=[entry[1] for entry in run.history], mode="lines+markers",
                        name=f"GA best{suffix}", marker={"size": 4})
        fig.add_scatter(x=generations, y=[entry[2] for entry in run.history], mode="lines",
                        name=f"GA mean{suffix}", line={"dash": "dot"})
        block = next((r for r in runs if r.solver == "Block packer" and r.family == run.family), None)
        # The block packer scored on the same objective: placed - penalty x (bound - placed).
        if block is not None:
            fig.add_hline(y=2 * block.cases_per_layer - block.target, line={"color": "#94a3b8", "dash": "dash"},
                          annotation_text="block packer", annotation_position="bottom right")
        fig.add_hline(y=run.target, line={"color": "#ef4444", "dash": "dash"},
                      annotation_text="bound (optimum)", annotation_position="top right")
    fig.update_layout(
        height=230,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        xaxis_title="Generation",
        yaxis_title="Objective",
        legend={"orientation": "h", "y": -0.35, "font": {"size": 10}},
    )
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    st.caption("Objective per layer = cases placed \u2212 cases short of the malleable bound, so the bound is "
               "the optimum. The best line never drops (elitism); the gap to the red line is what's left.")


def _placement_rows(result) -> list[dict]:
    layer_index = {z: n for n, z in enumerate(sorted({p.z for p in result.placements}), start=1)}
    return [
        {
            "#": index,
            "layer": layer_index[p.z],
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

    _section("Units")
    st.selectbox("System", list(UNIT_SYSTEMS), key="units", on_change=_convert_units,
                 help="Applies to every length and weight. Switching converts the values already entered.")
    p_unit, w_unit_label = _units()

    st.divider()
    _section("Pallet")
    st.selectbox("Preset", [*sorted(STANDARD_PALLETS), CUSTOM], key="preset", format_func=_preset_label,
                 on_change=_apply_preset)
    _num(f"Length ({p_unit})", "p_len", on_change=_mark_custom, min_value=0.001)
    _num(f"Width ({p_unit})", "p_wid", on_change=_mark_custom, min_value=0.001)
    _num(f"Max build height ({p_unit})", "p_height",
         help="Floor to top of load, including the pallet. Sets how many layers stack. "
              "0 = no limit (single layer).")
    _num(f"Deck height ({p_unit})", "p_deck", on_change=_mark_custom, min_value=0.001,
         help="The pallet's own height; counts toward the max build height.")
    _num(f"Max weight ({w_unit_label})", "p_maxw", on_change=_mark_custom, help="Total case weight. 0 = no limit.")
    with st.expander("More limits", expanded=False):
        _num(f"Max volume ({p_unit}³)", "p_maxvol", help="0 = no limit.")
        _num(f"Max plan area ({p_unit}²)", "p_maxarea", help="Combined case footprint. 0 = no limit.")

    st.divider()
    _section("Case")
    _num(f"Length ({p_unit})", "c_len", min_value=0.001)
    _num(f"Width ({p_unit})", "c_wid", min_value=0.001)
    _num(f"Height ({p_unit})", "c_hgt", min_value=0.001)
    _num(f"Weight ({w_unit_label})", "c_weight")
    st.toggle("This side up", key="c_tsu",
              help="Off lets the solver lay cases on a side or end. Every case in a layer still shares one "
                   "height, so each layer top stays flat.")

    st.divider()
    _section("Solve")
    st.toggle("GA layer search", key="ga_on",
              help="Genetic algorithm that targets the malleable bound (deck area / case footprint) per "
                   "layer and penalizes cases that don't fit. Runs where the block packer falls short.")
    if st.session_state.ga_on:
        st.number_input("Generations", key="ga_gens", min_value=1, max_value=500, step=1)
        st.number_input("Population", key="ga_pop", min_value=4, max_value=200, step=1)
        st.number_input("Seed", key="ga_seed", min_value=0, step=1)

ss = st.session_state
ga_args = (ss.ga_gens, ss.ga_pop, ss.ga_seed) if ss.ga_on else None
pallet_args = {
    "length": ss.p_len,
    "width": ss.p_wid,
    "height": ss.p_height or None,
    "unit": p_unit,
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
    "unit": p_unit,
    "this_side_up": ss.c_tsu,
}

# --- Main area: results ---------------------------------------------------------------------

try:
    pallet = Pallet(**pallet_args)
    with st.spinner("Solving…"):
        count, result, limit_violations = _solve(pallet_args, case_args, ga_args)
except ValueError as exc:
    st.error(f"Invalid input: {exc}")
    st.stop()

w_unit = w_unit_label
unit = pallet.unit
placed_weight = count * ss.c_weight
load_height = max((p.z + p.height for p in result.placements), default=0.0)
build_height = (pallet.deck_height or 0.0) + load_height

ok = count > 0
headline = f"{count} cases fit" if ok else "No cases fit"
if count:
    headline += f" · {result.layers} layer{'s' if result.layers != 1 else ''} × {result.cases_per_layer}"

pallet_name = pallet.name or "Custom pallet"
st.markdown(f"#### {headline}")
st.caption(
    f"{pallet_name} · {pallet.length:g}×{pallet.width:g} {unit} deck · "
    f"case {ss.c_len:g}×{ss.c_wid:g}×{ss.c_hgt:g} {p_unit}"
)

view_col, info_col = st.columns([1.5, 1], gap="large")
with view_col:
    if result.placements:
        view_3d, view_plan = st.tabs(["3D view", "Layer plan"])
        with view_3d:
            _render_3d(pallet, result)
        with view_plan:
            st.caption("Every full layer uses this same pattern; a partial top layer fills from case 1.")
            _render_plan(pallet, [p for p in result.placements if p.z == 0])
    else:
        st.info("Nothing to draw. Adjust the inputs in the sidebar.")

with info_col:
    limit_text = (
        f"Limit {pallet.height:g} {unit} (deck {pallet.deck_height or 0:g} + load {pallet.load_height_limit:g})"
        if pallet.height else "No build height limit"
    )
    m1, m2 = st.columns(2)
    m1.metric("Cases", count)
    m2.metric("Malleable bound", result.volume_bound,
              help="Cases that would fit if they were perfectly malleable: the space above the deck up to "
                   "the build height divided by case volume. Ignores weight and other limits.")
    m1.metric("Layers", f"{result.layers} × {result.cases_per_layer}" if count else "0",
              help=f"Layers × cases per layer. Up to {result.max_layers} layers fit the build height.")
    m2.metric("Cube use", f"{result.volume_utilization:.1%}" if pallet.height else "–",
              help="Case volume as a share of the space above the deck up to the max build height.")
    m1.metric("Deck coverage", f"{result.utilization:.1%}", help="Share of the deck covered by the base layer.")
    m2.metric(
        "Load weight",
        f"{placed_weight:,.1f} {w_unit}",
        help=f"Limit: {pallet.max_weight:,.1f} {w_unit}" if pallet.max_weight else "No weight limit",
    )
    m1.metric("Build height", f"{build_height:g} {unit}", help=f"Deck + load, from the floor. {limit_text}.")
    m2.metric("Headroom", f"{pallet.height - build_height:g} {unit}" if pallet.height else "–",
              help="Space left under the max build height.")

    if ok:
        if count == result.capacity:
            if pallet.height:
                st.info(f"Limited by **pallet space**: {result.max_layers} layers of {result.cases_per_layer} "
                        f"fill the build height.")
            else:
                st.info("Single layer: set a **max build height** to stack layers.")
        elif limit_violations:
            st.info(f"Limited by **{_limit_reason(limit_violations)}**: one more case would break it.")
    if not ok and result.violations:
        st.error("\n".join(f"- {v}" for v in _summarize_violations(result.violations)))

    rotated = sum(1 for p in result.placements if p.orientation[:2] != (0, 1))
    tipped = sum(1 for p in result.placements if p.orientation[2] != 2)
    partial = count - (result.layers - 1) * result.cases_per_layer if count else 0
    top_note = f" · top layer {partial} of {result.cases_per_layer}" if count and partial < result.cases_per_layer else ""
    st.caption(f"{count - rotated} as entered · {rotated} rotated · {tipped} tipped{top_note}")
    _render_solver_status(result)

table_tab, export_tab = st.tabs(["Placements", "Export"])
with table_tab:
    st.dataframe(_placement_rows(result), hide_index=True, width="stretch", height=300)
with export_tab:
    payload = {
        "pallet": pallet_args,
        "case": case_args,
        "weight_unit": w_unit,
        "ga": {"generations": ga_args[0], "population": ga_args[1], "seed": ga_args[2]} if ga_args else None,
        "result": {
            "cases": count,
            "feasible": ok,
            "layers": result.layers,
            "cases_per_layer": result.cases_per_layer,
            "max_layers": result.max_layers,
            "build_height": build_height,
            "deck_coverage": result.utilization,
            "cube_utilization": result.volume_utilization,
            "placed_weight": placed_weight,
            "malleable_bound": result.volume_bound,
            "solver_runs": [
                {"solver": r.solver, "family": r.family, "ran": r.ran, "selected": r.selected,
                 "cases_per_layer": r.cases_per_layer, "target": r.target, "note": r.note,
                 "history": [list(h) for h in r.history]}
                for r in result.solver_runs
            ],
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
