from __future__ import annotations

import io
import json
import time

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
SENS_FIXED, SENS_PCT = "Fixed amount", "Percent"
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
        section[data-testid="stSidebar"] { min-width: 400px; }
        /* Compact value boxes: shorter inputs and selects with less vertical padding. */
        section[data-testid="stSidebar"] [data-baseweb="input"],
        section[data-testid="stSidebar"] [data-baseweb="select"] > div { min-height: 1.85rem; height: 1.85rem; }
        section[data-testid="stSidebar"] [data-baseweb="input"] input { padding-top: 0.1rem; padding-bottom: 0.1rem; }
        section[data-testid="stSidebar"] [data-baseweb="select"] > div > div { padding-top: 0; padding-bottom: 0; }
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
    # Keep the sensitivity step on the round default for the new system unless the user changed it.
    step = st.session_state.sens_step
    if abs(step - DEFAULT_SENS_STEP[old_length]) < 1e-9:
        st.session_state.sens_step = DEFAULT_SENS_STEP[new_length]
    else:
        st.session_state.sens_step = _round(convert_length(step, old_length, new_length))
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
        sens_mode=SENS_FIXED,
        sens_step=DEFAULT_SENS_STEP["in"],
        sens_pct=DEFAULT_SENS_PCT,
        sens_steps=1,
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
    st.dataframe(_solver_rows(result), hide_index=True, width="stretch", column_config=_SOLVER_COLUMNS)
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


def _summary_rows(pallet: Pallet, result, count: int, units: tuple[str, str], extra: dict) -> list[dict]:
    length_unit, weight_unit = units
    rows = {
        "Pallet": pallet.name or "Custom",
        f"Deck length ({length_unit})": pallet.length,
        f"Deck width ({length_unit})": pallet.width,
        f"Deck height ({length_unit})": pallet.deck_height,
        f"Max build height ({length_unit})": pallet.height,
        f"Max weight ({weight_unit})": pallet.max_weight,
        **extra,
        "Cases": count,
        "Layers": result.layers,
        "Cases per layer": result.cases_per_layer,
        "Max layers": result.max_layers,
        "Malleable bound": result.volume_bound,
        "Stacking": STACKING_LABELS.get(result.stacking, result.stacking),
        "Alternate layers": FLIP_LABELS.get(result.flip, result.flip),
        "Interlock": round(result.interlock, 4),
        "Min support": round(result.min_support, 4),
        "Deck coverage": round(result.utilization, 4),
        "Cube use": round(result.volume_utilization, 4),
    }
    return [{"Field": key, "Value": value} for key, value in rows.items()]


def _excel_bytes(sheets: dict[str, list[dict]]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            frame = pd.DataFrame(rows)
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            for column, header in zip(sheet.columns, frame.columns):  # fit column widths to content
                width = max([len(str(header)), *(len(str(cell.value)) for cell in column if cell.value is not None)])
                sheet.column_dimensions[column[0].column_letter].width = min(width + 2, 60)
    return buffer.getvalue()


_SENS_DIMENSIONS = (("Length", ("length",)), ("Width", ("width",)), ("Height", ("height",)),
                    ("All three", ("length", "width", "height")))


def _sensitivity(solve, case_args: dict, base_count: int, fixed: bool, amount: float, steps: int,
                 unit: str) -> tuple[list[dict], list[str]]:
    """Case counts with each dimension (and all three) changed by +/- ``steps`` x ``amount``.

    ``solve(case_args)`` returns the case count for a variant. Returns one row per dimension and the
    ordered column labels; variants that would make a dimension non-positive are left blank.
    """
    offsets = [k for k in range(-steps, steps + 1)]
    labels = [("Base" if k == 0 else (f"{k * amount:+g} {unit}" if fixed else f"{k * amount:+g}%")) for k in offsets]
    rows = []
    for name, keys in _SENS_DIMENSIONS:
        row: dict = {"Dimension": name}
        for k, label in zip(offsets, labels):
            if k == 0:
                row[label] = base_count
                continue
            variant = dict(case_args)
            for key in keys:
                variant[key] = round(case_args[key] + k * amount if fixed else case_args[key] * (1 + k * amount / 100), 6)
            row[label] = solve(variant) if all(variant[key] > 0 for key in keys) else None
        rows.append(row)
    return rows, labels


def _render_sensitivity(rows: list[dict], labels: list[str], base_count: int, unit: str) -> None:
    def shade(value):
        if value is None or pd.isna(value) or value == base_count:
            return ""
        return "background-color: #dcfce7; color: #166534" if value > base_count else \
            "background-color: #fee2e2; color: #991b1b"

    frame = pd.DataFrame(rows).set_index("Dimension")[labels]
    st.dataframe(frame.style.map(shade).format("{:.0f}", na_rep="\u2013"), width="content")
    fig = go.Figure()
    for row in rows:
        fig.add_scatter(x=labels, y=[row[label] for label in labels], mode="lines+markers", name=row["Dimension"])
    fig.add_hline(y=base_count, line={"color": "#94a3b8", "dash": "dash"}, annotation_text="base",
                  annotation_position="top left")
    fig.update_layout(height=260, margin={"l": 0, "r": 0, "t": 10, "b": 0}, yaxis_title="Cases",
                      xaxis_title=f"Change in case size ({unit} or %)", legend={"orientation": "h", "y": -0.3})
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    st.caption("Each variant is a full re-solve with the same pallet, stacking and solver settings. Green = more "
               "cases than the base, red = fewer. Useful for spotting sizes near a threshold, where a small "
               "change in packaging adds or loses a row, column or layer.")


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

    st.divider()
    _section("Sensitivity")
    st.toggle("Case size sensitivity", key="sens_on",
              help="Re-solve with each case dimension (and all three together) increased and reduced.")
    sens_off = not st.session_state.sens_on
    st.selectbox("Change by", [SENS_FIXED, SENS_PCT], key="sens_mode", disabled=sens_off)
    st.number_input(f"Step ({p_unit})", key="sens_step", min_value=0.001, step=0.1, format="%g",
                    disabled=sens_off or st.session_state.sens_mode != SENS_FIXED)
    st.number_input("Step (%)", key="sens_pct", min_value=0.1, max_value=50.0, step=0.5, format="%g",
                    disabled=sens_off or st.session_state.sens_mode != SENS_PCT)
    st.number_input("Steps each way", key="sens_steps", min_value=1, max_value=5, step=1, disabled=sens_off)

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

sens_rows: list[dict] = []
sens_labels: list[str] = []
if ss.sens_on and count:
    fixed = ss.sens_mode == SENS_FIXED
    with st.spinner("Running sensitivity\u2026"):
        sens_rows, sens_labels = _sensitivity(
            lambda variant: _solve(pallet_args, variant, ga_args, ss.stacking, min_support)[0],
            case_args, count, fixed, ss.sens_step if fixed else ss.sens_pct, ss.sens_steps, p_unit,
        )

placement_rows = _placement_rows(result)
view_col, info_col = st.columns(2, gap="large")
with view_col:
    view_tab, table_tab, sens_tab = st.tabs(["3D view", "Placements", "Sensitivity"])
    with view_tab:
        if result.placements:
            _render_3d(pallet, result)
        else:
            st.info("Nothing to draw. Adjust the inputs in the sidebar.")
    with table_tab:
        st.dataframe(placement_rows, hide_index=True, width="content", height=380)
        settings = {
            "Stacking": STACKING_LABELS[ss.stacking],
            "Min support setting": min_support,
            "GA": f"{ga_args[0]} generations, population {ga_args[1]}, seed {ga_args[2]}" if ga_args else "off",
        }
        summary = _summary_rows(pallet, result, count, (p_unit, w_unit), settings)
        solver_rows = _solver_rows(result)
        history_rows = [
            {"Solver": run.solver, "Generation": h[0], "Best objective": h[1], "Mean objective": h[2], "Best interlock": h[3]}
            for run in result.solver_runs for h in run.history
        ]
        sheets = {"Summary": summary, "Placements": placement_rows, "Solver runs": solver_rows}
        if history_rows:
            sheets["GA history"] = history_rows
        if sens_rows:
            sheets["Sensitivity"] = sens_rows
        payload = {
            "pallet": pallet_args,
            "case": case_args,
            "weight_unit": w_unit,
            "settings": settings,
            "summary": {row["Field"]: row["Value"] for row in summary},
            "solver_runs": solver_rows,
            "ga_history": history_rows,
            "violations": result.violations,
            "placements": placement_rows,
            "sensitivity": sens_rows,
        }
        c1, c2, c3 = st.columns(3)
        c1.download_button("Excel (.xlsx)", _excel_bytes(sheets), file_name="pallet_layout.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
        c2.download_button("CSV (placements)", pd.DataFrame(placement_rows).to_csv(index=False),
                           file_name="pallet_layout.csv", mime="text/csv", width="stretch")
        c3.download_button("JSON", json.dumps(payload, indent=2, default=str), file_name="pallet_layout.json",
                           mime="application/json", width="stretch")
        st.caption("CSV is this placement grid. Excel adds Summary, Solver runs, GA history and Sensitivity "
                   "sheets; JSON has everything, including the inputs, so a run can be reproduced later.")
    with sens_tab:
        if sens_rows:
            _render_sensitivity(sens_rows, sens_labels, count, p_unit)
        else:
            st.info("Turn on case size sensitivity in the sidebar (and make sure at least one case fits).")

with info_col:
    summary_tab, iterations_tab = st.tabs(["Summary", "By iteration"])
    with summary_tab:
        limit_text = (
            f"Limit {pallet.height:g} {unit} (deck {pallet.deck_height or 0:g} + load {pallet.load_height_limit:g})"
            if pallet.height is not None else "No build height limit"
        )
        m1, m2 = st.columns(2)
        m1.metric("Cases", count)
        m2.metric("Malleable bound", result.volume_bound,
                  help="Cases that would fit if they were perfectly malleable: the space above the deck up to "
                       "the build height divided by case volume. Ignores weight and other limits.")
        m1.metric("Layers", f"{result.layers} × {result.cases_per_layer}" if count else "0",
                  help=f"Layers × cases per layer. Up to {result.max_layers} layers fit the build height.")
        m2.metric("Cube use", f"{result.volume_utilization:.1%}" if pallet.height is not None else "–",
                  help="Case volume as a share of the space above the deck up to the max build height.")
        m1.metric("Deck coverage", f"{result.utilization:.1%}", help="Share of the deck covered by the base layer.")
        m2.metric(
            "Load weight",
            f"{placed_weight:,.1f} {w_unit}",
            help=f"Limit: {pallet.max_weight:,.1f} {w_unit}" if pallet.max_weight is not None else "No weight limit",
        )
        m1.metric("Build height", f"{build_height:g} {unit}", help=f"Deck + load, from the floor. {limit_text}.")
        m2.metric("Headroom", f"{pallet.height - build_height:g} {unit}" if pallet.height is not None else "–",
                  help="Space left under the max build height.")
        stacked = result.layers >= 2 and result.stacking != "column"
        m1.metric("Interlock", f"{result.interlock:.0%}" if stacked else "–",
                  help="Share of cases resting on two or more cases in the layer below (bridging the seams).")
        m2.metric("Min support", f"{result.min_support:.0%}" if stacked else "–",
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
        top_note = f" · top layer {partial} of {result.cases_per_layer}" if count and partial < result.cases_per_layer else ""
        st.caption(f"{count - rotated} as entered · {rotated} rotated · {tipped} tipped{top_note}")
        if result.layers >= 2:
            layering = "every layer the same pattern" if result.flip == "none" else f"even layers {FLIP_LABELS[result.flip]}"
            st.caption(f"Stacking: {STACKING_LABELS[result.stacking].split(' (')[0].lower()} \u00b7 {layering}")
        if result.stacking_note:
            st.warning(result.stacking_note)
        _render_solver_status(result, solve_ms)
    with iterations_tab:
        _render_iterations(result)
