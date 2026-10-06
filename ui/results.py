"""Result tabs: Overview, Summary (with solver status), By iteration and Placements."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from pallet_builder import ALIGNMENT_LABELS, FLIP_LABELS, Pallet
from ui.solving import Solved, limit_text, solver_notes, summarize_violations
from ui.state import STACKING_LABELS


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


def _render_solver_status(result, solve_ms: float, cached: bool) -> None:
    if not result.solver_runs:
        return
    timing = f"cached (first solve took {solve_ms:,.0f} ms)" if cached else f"solved in {solve_ms:,.0f} ms"
    st.markdown(f"**Solver status** \u00b7 {timing}")
    rows = _solver_rows(result)
    # Streamlit's auto-fit doesn't widen long text, and it can only wrap when every row is over 4rem
    # tall (no per-row heights), so size the Note column to its longest entry instead.
    longest = max((len(row["Note"]) for row in rows), default=0)
    columns = {**_SOLVER_COLUMNS, "Note": st.column_config.TextColumn(width=min(max(round(7.5 * longest) + 32, 120), 900))}
    st.dataframe(rows, hide_index=True, width="stretch", column_config=columns)
    st.caption("Iterations: block packer = region states solved, GA = generations. Evaluations: block packer = "
               "cuts tried, GA = distinct patterns decoded. Times are from the first solve (results are cached).")


def render_iterations(result) -> None:
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
    st.caption("Objective per layer = cases placed \u2212 cases short of the bound (deck area \u00f7 case footprint), so the bound is the "
               "count optimum, plus up to +1 for interlock when stacking interlocks. The best line never drops "
               "(elitism).")


def placement_rows(result) -> list[dict]:
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


_OVERVIEW = """
### What Pallet Builder is for

Pallet Builder works out **how many identical cases fit on a pallet and exactly how to stack them**. Use it to
compare case sizes and pallet patterns, so each pallet carries as many cases as it safely can: fewer pallets
shipped and stored per unit, within the pallet's weight rating and the height you can load to, and with layers
that lock together instead of standing in loose columns.

### How to use it

1. Set everything on the **Input** tab: units, pallet, build limits, case and solver settings. The **Result**
   section at the bottom of that tab shows every calculated metric, so you see the effect of each edit there.
2. Read the outcome on **Summary**, look at the stack in **3D view**, and get case-by-case positions from
   **Placements**.
3. Use **Sensitivity** to see whether a slightly different case size would fit more, and how tight your tolerances
   need to be.

With **Auto-solve** on, results update as you type; turn it off for heavy settings (for example a long GA run)
and press **Solve** when ready. The 3D view, Placements, By iteration and Sensitivity tabs only compute while
they're open, so editing stays quick. Each result tab starts with a summary of the inputs it was solved from.
Save your inputs as a **.pallet** file, or start from a built-in sample.

### How it solves

- **One layer pattern**: a *block packer* fills the deck with grids of cases, cutting it into blocks where that
  fits more. Where it falls short of the *bound* (deck area \u00f7 case footprint), a *genetic algorithm (GA)*
  searches for denser or better-interlocking patterns, running either a fixed number of generations or until it
  stops improving. The best layer wins.
- **Flat layers**: every case in a layer stands the same way up, so layers = (build height \u2212 deck) \u00f7
  case height, capped by the weight and other limits. *Ti* is the cases per layer and *Hi* the number of layers.
- **Layer alignment**: when a pattern doesn't fill the deck, layers can sit on *alternate sides* (flipped layers
  mirror across the deck), *flush to two sides*, or *centred* (best balance).
- **Interlocking**: alternate layers can be mirrored or turned 180\u00b0 so cases bridge the seams below, as
  long as each case keeps its minimum support. This never costs a case unless you forbid column stacking.

### The tabs

| Tab | What it shows |
|---|---|
| **Overview** | This page: what the app is for, how to use it, and how it solves |
| **Input** | Load a sample, open or save a .pallet file, or reset to defaults; then every input: units, pallet (preset or custom, deck height, max weight), build limits (max build height including the pallet, optional volume and plan area; blank = no limit), case (size, weight, this side up) and solve settings (Auto-solve, stacking, layer alignment, minimum support, GA stop rule, generations, population, seed); and at the bottom the **Result**: every calculated metric and what limits the count |
| **Summary** | The inputs it was solved from; cases, layers (Hi \u00d7 Ti), max by volume, cube use, deck coverage, load weight, build height, headroom, interlock and minimum support; what limits the count; how the layers stack; solver notes on any limits that applied; and the solver status table (each solver's result, work done and time) |
| **3D view** | The built pallet: drag to spin, scroll to zoom, buttons for iso, front, side and top views. Brown is the pallet deck, layers alternate shades, red dashes mark the max build height |
| **Placements** | Every case's number, layer, pattern (A, or B for flipped layers), position (x, y, z), size, and whether it's rotated or tipped. Download as CSV from the table toolbar |
| **By iteration** | How the GA's best and average objective (and interlock) improved, generation by generation, against the bound and the block packer's result; or why the GA didn't run |
| **Sensitivity** | Re-solves every combination of slightly bigger or smaller case lengths, widths and heights (each with its own step settings), then lists **opportunities** (changes that add cases, smallest first) and **risks** (smallest changes that lose cases), above a ranked table with the base case highlighted |

One case type per pallet. Stability is judged by interlock and support; crush strength and center of gravity
are not modeled yet.
"""


def render_overview() -> None:
    st.markdown(_OVERVIEW)


def _fmt(value: float) -> str:
    return f"{value:,.6g}"


def input_summary(pallet: Pallet, case_args: dict, stacking: str, min_support: float, ga: tuple | None,
                  weight_unit: str, stale: bool, alignment: str = "alternate") -> str:
    """What the results on a tab were solved from: pallet, build limits, case and solve settings."""
    unit = pallet.unit
    pallet_text = (f"{pallet.name or 'Custom'} {_fmt(pallet.length)} × {_fmt(pallet.width)} {unit}, "
                   f"deck {_fmt(pallet.deck_height or 0)} {unit}, max weight "
                   + (f"{_fmt(pallet.max_weight)} {weight_unit}" if pallet.max_weight is not None else "none"))
    build = [f"max height {_fmt(pallet.height)} {unit}" if pallet.height is not None else "no height limit (one layer)"]
    if pallet.max_volume is not None:
        build.append(f"max volume {_fmt(pallet.max_volume)} {unit}³")
    if pallet.max_plan_area is not None:
        build.append(f"max plan area {_fmt(pallet.max_plan_area)} {unit}²")
    case_text = (f"{_fmt(case_args['length'])} × {_fmt(case_args['width'])} × {_fmt(case_args['height'])} "
                 f"{unit}, {_fmt(case_args['weight'])} {weight_unit}, "
                 + ("this side up" if case_args["this_side_up"] else "may be tipped"))
    solve_text = STACKING_LABELS[stacking].split(" (")[0].lower()
    if stacking != "column":
        solve_text += f" (min support {min_support:.0%})"
    solve_text += f", layers {ALIGNMENT_LABELS[alignment].lower()}"
    if ga is None:
        solve_text += ", GA off"
    else:
        stop = f"stop after {ga[3]} without improvement, max {ga[0]}" if ga[3] else f"{ga[0]} generations"
        solve_text += f", GA {stop}, population {ga[1]}, seed {ga[2]}"
    parts = [f"<b>Pallet</b> {pallet_text}", f"<b>Build</b> {', '.join(build)}", f"<b>Case</b> {case_text}",
             f"<b>Solve</b> {solve_text}"]
    text = " · ".join(parts)
    if stale:
        text += " · <em>inputs have changed since this solve: press Solve on the Input tab</em>"
    return text


def render_input_summary(text: str) -> None:
    st.markdown(f"<div class='input-summary'>{text}</div>", unsafe_allow_html=True)


def render_metrics(pallet: Pallet, solved: Solved, case_args: dict, weight_unit: str) -> None:
    """Every calculated result: the metric grid, what limits the count, and how the layers are built.

    Shown both in the Input tab's Result section and at the top of the Summary tab.
    """
    result, count = solved.result, solved.count
    unit = pallet.unit
    load_height = max((p.z + p.height for p in result.placements), default=0.0)
    build_height = (pallet.deck_height or 0.0) + load_height
    stacked = result.layers >= 2 and result.stacking != "column"
    height_limit = (
        f"Limit {pallet.height:g} {unit} (deck {pallet.deck_height or 0:g} + load {pallet.load_height_limit:g})"
        if pallet.height is not None else "No build height limit"
    )
    if stacked:
        interlock = f"{result.interlock:.0%}" + (" (none found)" if result.interlock == 0 else "")
    else:
        interlock = "n/a"
    row1 = st.columns(5)
    row1[0].metric("Cases", count)
    row1[1].metric("Layers", f"{result.layers} layers \u00d7 {result.cases_per_layer}" if count else "0",
                   help=f"Layers (Hi) \u00d7 cases per layer (Ti). Up to {result.max_layers} layers fit the build height.")
    row1[2].metric("Max by volume", result.volume_bound,
                   help="An upper bound: how many cases would fit if they could fill the space perfectly (the space "
                        "above the deck up to the build height divided by case volume). Ignores weight and shape.")
    row1[3].metric("Cube use", f"{result.volume_utilization:.1%}" if pallet.height is not None else "n/a",
                   help="Case volume as a share of the space above the deck up to the max build height.")
    row1[4].metric("Deck coverage", f"{result.utilization:.1%}", help="Share of the deck covered by the base layer.")
    row2 = st.columns(5)
    placed_weight = count * case_args["weight"]
    row2[0].metric("Load weight", f"{placed_weight:,.1f} {weight_unit}",
                   help=f"Limit: {pallet.max_weight:,.1f} {weight_unit}" if pallet.max_weight is not None
                   else "No weight limit")
    row2[1].metric("Build height", f"{build_height:g} {unit}", help=f"Deck + load, from the floor. {height_limit}.")
    row2[2].metric("Headroom", f"{pallet.height - build_height:g} {unit}" if pallet.height is not None else "n/a",
                   help="Space left under the max build height.")
    row2[3].metric("Interlock", interlock,
                   help="Share of cases resting on two or more cases in the layer below (bridging the seams). "
                        "'none found' means interlocking was tried but no flip keeps every case supported; "
                        "n/a means it doesn't apply (column stacking or a single layer).")
    row2[4].metric("Min support", f"{result.min_support:.0%}" if stacked else "n/a",
                   help="Smallest share of any case's base that rests on cases below.")

    limit = limit_text(solved, pallet)
    if limit:
        st.info(limit[0].upper() + limit[1:] + ".")
    if not count and result.violations:
        st.error("\n".join(f"- {v}" for v in summarize_violations(result.violations)))

    rotated = sum(1 for p in result.placements if p.orientation[:2] != (0, 1))
    tipped = sum(1 for p in result.placements if p.orientation[2] != 2)
    partial = count - (result.layers - 1) * result.cases_per_layer if count else 0
    top_note = (f" \u00b7 top layer {partial} of {result.cases_per_layer}"
                if count and partial < result.cases_per_layer else "")
    st.caption(f"{count - rotated} as entered \u00b7 {rotated} rotated \u00b7 {tipped} tipped{top_note}")
    if result.layers >= 2:
        layering = ("every layer the same pattern" if result.flip == "none"
                    else f"even layers {FLIP_LABELS[result.flip]}")
        st.caption(f"Stacking: {STACKING_LABELS[result.stacking].split(' (')[0].lower()} \u00b7 {layering}"
                   f" \u00b7 layers {ALIGNMENT_LABELS[result.alignment]} where the pattern leaves a gap")
    if result.stacking_note:
        st.warning(result.stacking_note)


def render_summary(pallet: Pallet, solved: Solved, case_args: dict, weight_unit: str) -> None:
    render_metrics(pallet, solved, case_args, weight_unit)
    result = solved.result
    notes = solver_notes(result, case_args)
    if notes:
        st.markdown("**Solver notes**")
        st.markdown("\n".join(f"- {note}" for note in notes))
    _render_solver_status(result, solved.solve_ms, solved.cached)


def render_placements(result) -> None:
    # Every grid has its own CSV download in its toolbar (hover the table), so no separate export.
    st.dataframe(placement_rows(result), hide_index=True, width="content", height=520)
