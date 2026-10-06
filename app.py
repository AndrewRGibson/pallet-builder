from __future__ import annotations

import math
import time
from itertools import product

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pallet_builder import (
    DEFAULT_MIN_SUPPORT,
    DEFAULT_STACKING,
    FLIP_LABELS,
    STANDARD_PALLETS,
    Case,
    Pallet,
    __version__,
    convert_length,
    maximize_case_count,
    solve_pallet_layout,
)
from pallet_builder.insights import Variant, sensitivity_insights

APP_VERSION = __version__
# One unit system applies to every length and weight in the app.
UNIT_SYSTEMS = {"US (in, lb)": ("in", "lb"), "Metric (cm, kg)": ("cm", "kg")}
WEIGHT_UNITS = {"lb": 0.45359237, "kg": 1.0}  # kilograms per unit
# Typical max build heights (floor to top of load, including the pallet) applied with a preset.
DEFAULT_BUILD_HEIGHT = {"in": 60.0, "cm": 180.0}
_LENGTH_KEYS = ("p_len", "p_wid", "p_deck", "p_height", "c_len", "c_wid", "c_hgt")
# Default fixed sensitivity step per length unit (0.2 in / 0.5 cm) and percentage step.
DEFAULT_SENS_STEP = {"in": 0.2, "cm": 0.5}
DEFAULT_SENS_PCT = 2.0
SENS_FIXED, SENS_PCT = "Fixed", "Percent"
# (label, case_args key) for the dimensions analysed independently.
SENS_DIMENSIONS = (("Length", "length"), ("Width", "width"), ("Height", "height"))


def _default_sens_config(length_unit: str) -> list[dict]:
    return [
        {"Dimension": name, "On": True, "By": SENS_FIXED, "Fixed step": DEFAULT_SENS_STEP[length_unit],
         "Percent step": DEFAULT_SENS_PCT, "Steps": 1}
        for name, _ in SENS_DIMENSIONS
    ]


def _sens_config() -> list[dict]:
    """The sensitivity settings with any pending edits from the settings table applied."""
    config = [dict(row) for row in st.session_state.sens_config]
    for index, changes in st.session_state.get("sens_editor", {}).get("edited_rows", {}).items():
        config[int(index)].update(changes)
    return config
_WEIGHT_KEYS = ("p_maxw", "c_weight")
CUSTOM = "Custom"
STACKING_LABELS = {
    "interlock": "Interlock when possible",
    "column": "Column (same pattern every layer)",
    "no_column": "No column stacking",
}
# Above this many cases the 3D view draws each layer as one block to stay responsive.
MAX_3D_CASES = 6000

st.set_page_config(page_title="Pallet Builder", page_icon="📦", layout="wide")
st.markdown(
    """
    <style>
        .block-container { padding-top: 2.75rem; padding-bottom: 0.5rem; }
        section[data-testid="stSidebar"] .block-container { padding-top: 0.6rem; }
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.2rem; }
        /* Clear separation between sidebar sections; rows within a section stay compact. */
        section[data-testid="stSidebar"] hr { margin: 1.1rem 0 0.6rem; }
        /* !important: Streamlit's own sidebar sizing otherwise wins. */
        section[data-testid="stSidebar"] { width: 400px !important; min-width: 400px !important; }
        /* Compact value boxes: 28px number and select boxes (Streamlit's default is 40px). */
        section[data-testid="stSidebar"] [data-testid="stNumberInputContainer"],
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] > div:last-child > div {
            height: 28px !important; min-height: 0 !important;
        }
        section[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] input {
            height: 26px !important; min-height: 0 !important; padding-top: 2px !important; padding-bottom: 2px !important;
        }
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] button {
            height: 26px !important; padding-top: 0 !important; padding-bottom: 0 !important;
        }
        /* Sidebar properties: label and value on one line. */
        section[data-testid="stSidebar"] [data-testid="stNumberInput"],
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] {
            display: flex; flex-direction: row; align-items: center; gap: 0.5rem;
        }
        section[data-testid="stSidebar"] [data-testid="stNumberInput"] > [data-testid="stWidgetLabel"],
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] > [data-testid="stWidgetLabel"] {
            flex: 0 0 40%; min-height: 0; margin: 0; padding: 0;
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
    def scale(key: str, factor: float) -> None:
        if st.session_state[key] is not None:  # blank = no limit
            st.session_state[key] = _round(st.session_state[key] * factor)

    factor = convert_length(1.0, old_length, new_length)
    for key in _LENGTH_KEYS:
        scale(key, factor)
    scale("p_maxvol", factor**3)
    scale("p_maxarea", factor**2)
    for key in _WEIGHT_KEYS:
        scale(key, WEIGHT_UNITS[old_weight] / WEIGHT_UNITS[new_weight])
    # Convert fixed sensitivity steps, keeping the round default (0.2 in / 0.5 cm) where unchanged.
    config = _sens_config()
    for row in config:
        if abs(row["Fixed step"] - DEFAULT_SENS_STEP[old_length]) < 1e-9:
            row["Fixed step"] = DEFAULT_SENS_STEP[new_length]
        else:
            row["Fixed step"] = max(round(convert_length(row["Fixed step"], old_length, new_length), 2), 0.01)
    st.session_state.sens_config = config
    st.session_state.pop("sens_editor", None)  # the table restarts from the converted settings
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
        p_maxvol=None,
        p_maxarea=None,
        c_len=12.0,
        c_wid=10.0,
        c_hgt=8.0,
        c_weight=20.0,
        c_tsu=True,
        stacking=DEFAULT_STACKING,
        min_support=DEFAULT_MIN_SUPPORT * 100,
        ga_on=True,
        ga_gens=40,
        ga_pop=24,
        ga_seed=0,
        sens_on=True,
        sens_config=_default_sens_config("in"),
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


def _limit(label: str, key: str, *, on_change=None, help: str | None = None) -> float | None:
    """An optional limit: blank means no limit, while 0 is a real (if strict) limit."""
    return st.number_input(label, key=key, min_value=0.0, value=None, step=1.0, format="%g",
                           placeholder="No limit", on_change=on_change, help=help)


# --- Solving --------------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=64)
def _solve(pallet_args: dict, case_args: dict, ga: tuple[int, int, int] | None, stacking: str, min_support: float):
    started = time.perf_counter()
    pallet = Pallet(**pallet_args)
    case = Case(**case_args)
    options = {"optimize": ga is not None, "stacking": stacking, "min_support": min_support}
    if ga is not None:
        options.update(optimization_generations=ga[0], optimization_population=ga[1], optimization_seed=ga[2])
    count, result = maximize_case_count(pallet, case, **options)
    # Re-solve one more case to explain what stops the count going higher.
    limit = (
        solve_pallet_layout(pallet, [Case(**{**case_args, "quantity": count + 1})], **options).violations
        if count else []
    )
    return count, result, limit, (time.perf_counter() - started) * 1000


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
    if pallet.height is not None:
        envelope = [(0.0, 0.0, 0.0, pallet.length, pallet.width, pallet.height)]
        traces.append(_box_edges(envelope, "#ef4444", 2, dash="dash"))

    def camera(eye_x, eye_y, eye_z, up_y=0.0, up_z=1.0):
        return {"scene.camera": {"eye": {"x": eye_x, "y": eye_y, "z": eye_z}, "up": {"x": 0, "y": up_y, "z": up_z}}}

    views = [("Iso", camera(1.5, -1.5, 1.1)), ("Front", camera(0, -2.3, 0.2)),
             ("Side", camera(2.3, 0, 0.2)), ("Top", camera(0, 0, 2.6, up_y=1.0, up_z=0.0))]
    fig = go.Figure(traces)
    unit = pallet.unit
    fig.update_layout(
        height=560,
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


def _solver_rows(result) -> list[dict]:
    return [
        {
            "Solver": run.solver,
            "Layers": run.family,
            "Per layer": run.cases_per_layer if run.ran else None,
            "Bound": run.target,
            # Percent (0-100) so the Excel export reads naturally too.
            "Interlock": round(run.interlock * 100, 1) if run.ran and run.interlock is not None else None,
            "Iterations": run.iterations if run.ran else None,
            "Evaluations": run.evaluations if run.ran else None,
            "Time (ms)": round(run.elapsed_ms, 1) if run.ran else None,
            "Used": run.selected,
            "Note": run.note,
        }
        for run in result.solver_runs
    ]


_SOLVER_COLUMNS = {
    # Pinned so they stay visible while scrolling right; numbers are right-aligned and formatted
    # consistently per column.
    "Solver": st.column_config.TextColumn(pinned=True),
    "Layers": st.column_config.TextColumn(pinned=True),
    "Per layer": st.column_config.NumberColumn(format="localized", alignment="right"),
    "Bound": st.column_config.NumberColumn(format="localized", alignment="right"),
    "Interlock": st.column_config.NumberColumn(format="%.0f%%", alignment="right"),
    "Iterations": st.column_config.NumberColumn(format="localized", alignment="right"),
    "Evaluations": st.column_config.NumberColumn(format="localized", alignment="right"),
    "Time (ms)": st.column_config.NumberColumn(format="%.1f", alignment="right"),
    "Used": st.column_config.CheckboxColumn(),
    "Note": st.column_config.TextColumn(),
}


def _render_solver_status(result, solve_ms: float) -> None:
    if not result.solver_runs:
        return
    st.markdown(f"**Solver status** \u00b7 solved in {solve_ms:,.0f} ms")
    rows = _solver_rows(result)
    # Streamlit's auto-fit doesn't widen long text, and it can only wrap when every row is over 4rem
    # tall (no per-row heights), so size the Note column to its longest entry instead.
    longest = max((len(row["Note"]) for row in rows), default=0)
    columns = {**_SOLVER_COLUMNS, "Note": st.column_config.TextColumn(width=min(max(round(7.5 * longest) + 32, 120), 900))}
    st.dataframe(rows, hide_index=True, width="stretch", column_config=columns)
    st.caption("Iterations: block packer = region states solved, GA = generations. Evaluations: block packer = "
               "cuts tried, GA = distinct patterns decoded. Times are from the first solve (results are cached).")


def _render_iterations(result) -> None:
    """GA objective (and interlock) by generation."""
    ga_runs = [run for run in result.solver_runs if run.history]
    if not ga_runs:
        skipped = next((run.note for run in result.solver_runs if run.solver.startswith("Genetic") and not run.ran), "")
        st.info("The GA didn't run for this solve, so there's no iteration history. " + skipped)
        return
    show_interlock = any(entry[3] > 0 for run in ga_runs for entry in run.history)
    fig = go.Figure()
    for run in ga_runs:
        generations = [entry[0] for entry in run.history]
        suffix = f" ({run.solver.removeprefix('Genetic algorithm').strip(' ()') or run.family})" if len(ga_runs) > 1 else ""
        fig.add_scatter(x=generations, y=[entry[1] for entry in run.history], mode="lines+markers",
                        name=f"GA best{suffix}", marker={"size": 4})
        fig.add_scatter(x=generations, y=[entry[2] for entry in run.history], mode="lines",
                        name=f"GA mean{suffix}", line={"dash": "dot"})
        if show_interlock:
            fig.add_scatter(x=generations, y=[entry[3] for entry in run.history], mode="lines", yaxis="y2",
                            name=f"Interlock{suffix}", line={"color": "#16a34a"})
    run = ga_runs[0]
    block = next((r for r in result.solver_runs if r.solver == "Block packer" and r.family == run.family), None)
    # The block packer scored on the same count objective: placed - penalty x (bound - placed).
    if block is not None:
        fig.add_hline(y=2 * block.cases_per_layer - block.target, line={"color": "#94a3b8", "dash": "dash"},
                      annotation_text="block packer", annotation_position="bottom right")
    fig.add_hline(y=run.target, line={"color": "#ef4444", "dash": "dash"},
                  annotation_text="bound", annotation_position="top right")
    layout = {
        "height": 480,
        "margin": {"l": 0, "r": 0, "t": 10, "b": 0},
        "xaxis_title": "Generation",
        "yaxis_title": "Objective",
        "legend": {"orientation": "h", "y": -0.35, "font": {"size": 10}},
    }
    if show_interlock:
        layout["yaxis2"] = {"title": "Interlock", "overlaying": "y", "side": "right", "range": [0, 1.05],
                            "tickformat": ".0%", "showgrid": False}
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    st.caption("Objective per layer = cases placed \u2212 cases short of the malleable bound (so the bound is the "
               "count optimum), plus up to +1 for interlock when stacking interlocks. The best line never drops "
               "(elitism).")


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
            "pattern": "B" if result.flip != "none" and layer_index[p.z] % 2 == 0 else "A",
            "rotated": p.orientation[:2] != (0, 1),
            "tipped": p.orientation[2] != 2,
        }
        for index, p in enumerate(result.placements, start=1)
    ]


def _sens_row(changes: dict[str, str], case_args: dict, count: int, result, base_count: int) -> dict:
    stacked = result.layers >= 2 and result.stacking != "column"
    return {
        **changes,  # one column per dimension: its change, or "\u2013" when unchanged
        "Case size": f"{case_args['length']:g} \u00d7 {case_args['width']:g} \u00d7 {case_args['height']:g}",
        "Cases": count,
        "\u0394 cases": count - base_count,
        "Ti": result.cases_per_layer if count else 0,
        "Hi": result.layers if count else 0,
        "Deck coverage (%)": round(result.utilization * 100, 1),
        "Cube use (%)": round(result.volume_utilization * 100, 1),
        "Interlock (%)": round(result.interlock * 100, 1) if stacked else None,
        # Hidden: exact numbers for the opportunities panel (columns starting "_" aren't displayed).
        "_variant": Variant(case_args["length"], case_args["width"], case_args["height"], count,
                            result.cases_per_layer if count else 0, result.layers if count else 0),
    }


def _fitness(row: dict) -> tuple:
    """Rank variants: most cases, then cube use, interlock and deck coverage."""
    return (row["Cases"], row["Cube use (%)"], row["Interlock (%)"] or 0.0, row["Deck coverage (%)"])


# Smallest case dimension a variant may have (matches the sidebar's minimum case size).
MIN_CASE_DIMENSION = 0.001
# Steps each way are capped: every combination is solved, so 3 steps on all three dimensions is
# already 7 x 7 x 7 - 1 = 342 runs.
MAX_SENS_STEPS = 3


def _clean_sens_settings(settings: dict, length_unit: str) -> dict:
    """Coerce one dimension's settings to sensible values: positive steps, 0.1-50%, 1-3 steps."""

    def number(value, default: float) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) else default  # NaN or infinity -> default

    return {
        **settings,
        "On": bool(settings.get("On")),
        "By": settings.get("By") if settings.get("By") in (SENS_FIXED, SENS_PCT) else SENS_FIXED,
        "Fixed step": max(round(abs(number(settings.get("Fixed step"), DEFAULT_SENS_STEP[length_unit])), 2), 0.01),
        "Percent step": min(max(abs(number(settings.get("Percent step"), DEFAULT_SENS_PCT)), 0.1), 50.0),
        "Steps": int(min(max(round(number(settings.get("Steps"), 1)), 1), MAX_SENS_STEPS)),
    }


def _sens_options(settings: dict, name: str, key: str, case_args: dict, unit: str,
                  skipped: list[str]) -> list[tuple[str, float]]:
    """(change label, value) for one dimension: the base value plus each valid step either way."""
    options = [("\u2013", case_args[key])]
    if not settings["On"]:
        return options
    fixed = settings["By"] == SENS_FIXED
    amount = settings["Fixed step"] if fixed else settings["Percent step"]
    for k in range(-settings["Steps"], settings["Steps"] + 1):
        if k == 0:
            continue
        change = f"{k * amount:+g} {unit}" if fixed else f"{k * amount:+g}%"
        value = round(case_args[key] + k * amount if fixed else case_args[key] * (1 + k * amount / 100), 6)
        if value < MIN_CASE_DIMENSION:
            skipped.append(f"{name} {change} (would make the {key} {value:g} {unit})")
            continue
        options.append((change, value))
    return options


def _sens_variant_count(config: list[dict], case_args: dict, unit: str) -> int:
    total = 1
    for settings, (name, key) in zip(config, SENS_DIMENSIONS):
        total *= len(_sens_options(_clean_sens_settings(settings, unit), name, key, case_args, unit, []))
    return total - 1


def _sensitivity(solve, case_args: dict, base: tuple, config: list[dict], unit: str,
                 progress=None) -> tuple[list[dict], list[str]]:
    """Re-solve every combination of case-size changes: each dimension is either left alone or moved
    by one of its own steps, independently of the others.

    ``solve(case_args)`` returns (count, result); ``progress(done, total)`` is called after each
    solve. Returns the base row first, then the variants ranked by fitness (descending), plus a note
    for every step skipped because it would take a dimension below the minimum case size (so nothing
    is ever zero or negative).
    """
    base_count, base_result = base
    skipped: list[str] = []
    per_dimension = [
        _sens_options(_clean_sens_settings(settings, unit), name, key, case_args, unit, skipped)
        for settings, (name, key) in zip(config, SENS_DIMENSIONS)
    ]
    combos = [combo for combo in product(*per_dimension) if any(change != "\u2013" for change, _ in combo)]
    rows = []
    for done, combo in enumerate(combos, start=1):
        variant = dict(case_args)
        changes = {}
        for (name, key), (change, value) in zip(SENS_DIMENSIONS, combo):
            variant[key] = value
            changes[name] = change
        count, result = solve(variant)
        rows.append(_sens_row(changes, variant, count, result, base_count))
        if progress is not None:
            progress(done, len(combos))
    rows.sort(key=_fitness, reverse=True)
    base_changes = {name: "\u2013" for name, _ in SENS_DIMENSIONS}
    return [_sens_row(base_changes, case_args, base_count, base_result, base_count), *rows], skipped


_SENS_COLUMNS = {
    "Length": st.column_config.TextColumn(pinned=True, alignment="right", help="Change in case length"),
    "Width": st.column_config.TextColumn(pinned=True, alignment="right", help="Change in case width"),
    "Height": st.column_config.TextColumn(pinned=True, alignment="right", help="Change in case height"),
    "Case size": st.column_config.TextColumn(),
    # "Cases" becomes an in-cell bar scaled to the largest variant (set in _render_sensitivity).
    "Cases": st.column_config.NumberColumn(format="localized", alignment="right"),
    "\u0394 cases": st.column_config.NumberColumn(format="%+d", alignment="right"),
    "Ti": st.column_config.NumberColumn(format="localized", alignment="right", help="Cases per layer"),
    "Hi": st.column_config.NumberColumn(format="localized", alignment="right", help="Layers"),
    # In-cell bars make the shifts easy to compare down the ranking.
    "Deck coverage (%)": st.column_config.ProgressColumn("Deck coverage", format="%.1f%%", min_value=0, max_value=100),
    "Cube use (%)": st.column_config.ProgressColumn("Cube use", format="%.1f%%", min_value=0, max_value=100),
    "Interlock (%)": st.column_config.ProgressColumn("Interlock", format="%.0f%%", min_value=0, max_value=100),
}

_SENS_EDITOR_COLUMNS = {
    "Dimension": st.column_config.TextColumn(disabled=True),
    "On": st.column_config.CheckboxColumn(),
    "By": st.column_config.SelectboxColumn(options=[SENS_FIXED, SENS_PCT], required=True),
    # 2 dp: the step setting also limits how precisely a value can be entered.
    "Fixed step": st.column_config.NumberColumn(min_value=0.01, step=0.01, format="%.2f", required=True),
    "Percent step": st.column_config.NumberColumn(min_value=0.1, max_value=50.0, step=0.5, format="%g%%", required=True),
    "Steps": st.column_config.NumberColumn("Steps each way", min_value=1, max_value=MAX_SENS_STEPS, step=1, format="%d",
                                           required=True),
}


_INSIGHT_STYLE = {"gain": (st.success, ":material/trending_up:"), "risk": (st.warning, ":material/warning:"),
                  "info": (st.info, ":material/info:")}


def _render_opportunities(rows: list[dict], unit: str, max_weight: float | None, case_weight: float) -> None:
    insights = sensitivity_insights(rows[0]["_variant"], [row["_variant"] for row in rows[1:]], unit,
                                    max_weight=max_weight, case_weight=case_weight)
    st.markdown("**Opportunities and risks**")
    for insight in insights:
        box, icon = _INSIGHT_STYLE[insight.kind]
        box(insight.text, icon=icon)


def _render_sensitivity(rows: list[dict]) -> None:
    # Drop hidden fields (e.g. "_variant") before display: they aren't table data.
    frame = pd.DataFrame([{k: v for k, v in row.items() if not k.startswith("_")} for row in rows])

    def highlight(row):
        if row.name == 0:  # the base case is always the first row
            return ["background-color: #dbeafe; font-weight: 700"] * len(row)
        return [""] * len(row)

    def delta_color(value):
        if pd.isna(value) or value == 0:
            return ""
        return "color: #166534; font-weight: 600" if value > 0 else "color: #991b1b; font-weight: 600"

    styled = frame.style.apply(highlight, axis=1).map(delta_color, subset=["\u0394 cases"])
    columns = {**_SENS_COLUMNS, "Cases": st.column_config.ProgressColumn(
        "Cases", format="%d", min_value=0, max_value=max(int(frame["Cases"].max()), 1))}
    st.dataframe(styled, hide_index=True, width="stretch", height=min(38 + 35 * len(frame), 420),
                 column_config=columns)
    st.caption("Base case highlighted; variants ranked by fitness: most cases, then cube use, interlock and deck "
               "coverage. Each combination is a full re-solve with the same pallet, stacking and solver settings.")


_OVERVIEW = """
### What Pallet Builder is for

Pallet Builder works out **how many identical cases fit on a pallet and exactly how to stack them**. Use it to
compare case sizes and pallet patterns, so each pallet carries as many cases as it safely can: fewer pallets
shipped and stored per unit, within the pallet's weight rating and the height you can load to, and with layers
that lock together instead of standing in loose columns.

### How to use it

Set everything in the sidebar; results update as you type.

1. **Units**: US (in, lb) or Metric (cm, kg) for every length and weight.
2. **Pallet**: a standard preset (CHEP, GMA, EUR) or custom deck size, its deck height and rated max weight.
3. **Build**: the max build height from the floor (including the pallet), plus optional volume and plan-area
   limits. Leave a limit blank for no limit.
4. **Case**: length, width, height, weight, and whether it must stay *this side up*.
5. **Solve**: how layers stack (interlocked, column, or no columns), the minimum support for each case, and the
   genetic algorithm (GA) settings.

### How it solves

- **One layer pattern**: a *block packer* fills the deck with grids of cases, cutting it into blocks where that
  fits more. Where it falls short of the *malleable bound* (deck area \u00f7 case footprint), a *GA* searches for
  denser or better-interlocking patterns. The best layer wins.
- **Flat layers**: every case in a layer stands the same way up, so layers = (build height \u2212 deck) \u00f7 case
  height, capped by the weight and other limits.
- **Interlocking**: alternate layers can be mirrored or turned 180\u00b0 so cases bridge the seams below, as
  long as each case keeps its minimum support. This never costs a case unless you forbid column stacking.

### The tabs

| Tab | What it shows |
|---|---|
| **Summary** | Case count, Ti \u00d7 Hi, cube use, weight, height, interlock, what limits the count, and which solvers ran |
| **3D view** | The built pallet: drag to spin, scroll to zoom, buttons for iso, front, side and top views |
| **Placements** | Every case's layer, position and orientation (download as CSV from the table toolbar) |
| **By iteration** | How the GA's objective and interlock improved, generation by generation |
| **Sensitivity** | How the result changes if the case gets slightly bigger or smaller in any combination of dimensions |

One case type per pallet. Stability is judged by interlock and support; crush strength and center of gravity
are not modeled yet.
"""


def _render_overview() -> None:
    st.markdown(_OVERVIEW)


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
    _num(f"Deck height ({p_unit})", "p_deck", on_change=_mark_custom, min_value=0.001,
         help="The pallet's own height; counts toward the max build height.")
    _limit(f"Max weight ({w_unit_label})", "p_maxw", on_change=_mark_custom,
           help="Total case weight the pallet is rated for. Blank = no limit.")

    st.divider()
    _section("Build")
    _limit(f"Max build height ({p_unit})", "p_height",
           help="Floor to top of load, including the pallet. Sets how many layers stack. "
                "Blank = no limit (a single layer).")
    _limit(f"Max volume ({p_unit}\u00b3)", "p_maxvol", help="Total case volume. Blank = no limit.")
    _limit(f"Max plan area ({p_unit}\u00b2)", "p_maxarea", help="Combined case footprint. Blank = no limit.")

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
    st.selectbox("Stacking", list(STACKING_LABELS), key="stacking", format_func=STACKING_LABELS.get,
                 help="Interlock flips every other layer (mirror or 180\u00b0 turn) when that makes cases bridge "
                      "the seams below, without costing a case. 'No column stacking' requires interlock and may "
                      "trade cases for it; if no pattern interlocks, the load is limited to one layer.")
    # Inputs that don't apply are disabled rather than hidden: Streamlit drops the stored value of a
    # widget that isn't drawn, which would silently reset it to its minimum when shown again.
    st.number_input("Min support (%)", key="min_support", min_value=0.0, max_value=100.0, step=5.0, format="%g",
                    disabled=st.session_state.stacking == "column",
                    help="Each case must have at least this share of its base resting on cases below.")
    st.toggle("GA layer search", key="ga_on",
              help="Genetic algorithm that targets the malleable bound (deck area / case footprint) per "
                   "layer and penalizes cases that don't fit. Runs where the block packer falls short.")
    ga_off = not st.session_state.ga_on
    st.number_input("Generations", key="ga_gens", min_value=1, max_value=500, step=1, disabled=ga_off)
    st.number_input("Population", key="ga_pop", min_value=4, max_value=200, step=1, disabled=ga_off)
    st.number_input("Seed", key="ga_seed", min_value=0, step=1, disabled=ga_off)


ss = st.session_state
ga_args = (ss.ga_gens, ss.ga_pop, ss.ga_seed) if ss.ga_on else None
min_support = ss.min_support / 100
pallet_args = {
    "length": ss.p_len,
    "width": ss.p_wid,
    "height": ss.p_height,
    "unit": p_unit,
    "max_weight": ss.p_maxw,
    "max_volume": ss.p_maxvol,
    "max_plan_area": ss.p_maxarea,
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
        count, result, limit_violations, solve_ms = _solve(pallet_args, case_args, ga_args, ss.stacking, min_support)
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

placement_rows = _placement_rows(result)
overview_tab, summary_tab, view_tab, table_tab, iterations_tab, sens_tab = st.tabs(
    ["Overview", "Summary", "3D view", "Placements", "By iteration", "Sensitivity"])

with overview_tab:
    _render_overview()

with summary_tab:
    limit_text = (
        f"Limit {pallet.height:g} {unit} (deck {pallet.deck_height or 0:g} + load {pallet.load_height_limit:g})"
        if pallet.height is not None else "No build height limit"
    )
    stacked = result.layers >= 2 and result.stacking != "column"
    row1 = st.columns(5)
    row1[0].metric("Cases", count)
    row1[1].metric("Layers", f"{result.layers} \u00d7 {result.cases_per_layer}" if count else "0",
                   help=f"Layers \u00d7 cases per layer. Up to {result.max_layers} layers fit the build height.")
    row1[2].metric("Malleable bound", result.volume_bound,
                   help="Cases that would fit if they were perfectly malleable: the space above the deck up to "
                        "the build height divided by case volume. Ignores weight and other limits.")
    row1[3].metric("Cube use", f"{result.volume_utilization:.1%}" if pallet.height is not None else "\u2013",
                   help="Case volume as a share of the space above the deck up to the max build height.")
    row1[4].metric("Deck coverage", f"{result.utilization:.1%}", help="Share of the deck covered by the base layer.")
    row2 = st.columns(5)
    row2[0].metric(
        "Load weight",
        f"{placed_weight:,.1f} {w_unit}",
        help=f"Limit: {pallet.max_weight:,.1f} {w_unit}" if pallet.max_weight is not None else "No weight limit",
    )
    row2[1].metric("Build height", f"{build_height:g} {unit}", help=f"Deck + load, from the floor. {limit_text}.")
    row2[2].metric("Headroom", f"{pallet.height - build_height:g} {unit}" if pallet.height is not None else "\u2013",
                   help="Space left under the max build height.")
    row2[3].metric("Interlock", f"{result.interlock:.0%}" if stacked else "\u2013",
                   help="Share of cases resting on two or more cases in the layer below (bridging the seams).")
    row2[4].metric("Min support", f"{result.min_support:.0%}" if stacked else "\u2013",
                   help="Smallest share of any case's base that rests on cases below.")

    if ok:
        if count == result.capacity:
            if pallet.height is not None:
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
    top_note = f" \u00b7 top layer {partial} of {result.cases_per_layer}" if count and partial < result.cases_per_layer else ""
    st.caption(f"{count - rotated} as entered \u00b7 {rotated} rotated \u00b7 {tipped} tipped{top_note}")
    if result.layers >= 2:
        layering = "every layer the same pattern" if result.flip == "none" else f"even layers {FLIP_LABELS[result.flip]}"
        st.caption(f"Stacking: {STACKING_LABELS[result.stacking].split(' (')[0].lower()} \u00b7 {layering}")
    if result.stacking_note:
        st.warning(result.stacking_note)
    _render_solver_status(result, solve_ms)

with view_tab:
    if result.placements:
        _render_3d(pallet, result)
    else:
        st.info("Nothing to draw. Adjust the inputs in the sidebar.")

with table_tab:
    # Every grid has its own CSV download in its toolbar (hover the table), so no separate export.
    st.dataframe(placement_rows, hide_index=True, width="content", height=520)

with iterations_tab:
    _render_iterations(result)

with sens_tab:
    st.toggle("Run case size sensitivity", key="sens_on",
              help="Re-solve every combination of case-size changes: each dimension is unchanged or "
                   "moved by one of its own steps.")
    edited = st.data_editor(pd.DataFrame(ss.sens_config), key="sens_editor", hide_index=True, width="content",
                            column_config={**_SENS_EDITOR_COLUMNS, "Fixed step": {
                                **_SENS_EDITOR_COLUMNS["Fixed step"], "label": f"Fixed step ({p_unit})"}},
                            disabled=not ss.sens_on, num_rows="fixed")
    if ss.sens_on and count:
        config = edited.to_dict("records")
        st.caption(f"{_sens_variant_count(config, case_args, p_unit)} combinations: each dimension is "
                   "either unchanged or moved by one of its steps.")
        bar = st.progress(0.0, text="Running sensitivity\u2026")
        sens_rows, sens_skipped = _sensitivity(
            lambda variant: _solve(pallet_args, variant, ga_args, ss.stacking, min_support)[:2],
            case_args, (count, result), config, p_unit,
            progress=lambda done, total: bar.progress(done / total, text=f"Sensitivity: {done} of {total}"),
        )
        bar.empty()
        if len(sens_rows) > 1:
            _render_opportunities(sens_rows, p_unit, pallet.max_weight, ss.c_weight)
            _render_sensitivity(sens_rows)
            if sens_skipped:
                st.caption("Skipped (a case dimension can't be zero or negative): " + "; ".join(sens_skipped) + ".")
        else:
            st.info("Turn on at least one dimension above.")
    elif ss.sens_on:
        st.info("No cases fit the base case, so there's nothing to compare against.")
