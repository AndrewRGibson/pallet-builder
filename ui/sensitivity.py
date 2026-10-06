"""Case-size sensitivity: re-solve every combination of length/width/height changes and explain it."""

from __future__ import annotations

import math
from itertools import product

import pandas as pd
import streamlit as st

from pallet_builder.insights import Variant, sensitivity_insights
from ui.state import (
    DEFAULT_SENS_PCT,
    DEFAULT_SENS_STEP,
    SENS_DIMENSIONS,
    SENS_FIXED,
    SENS_PCT,
)


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


# Smallest case dimension a variant may have (matches the Input tab's minimum case size).
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


def render_tab(solve, case_args: dict, base: tuple, unit: str, max_weight: float | None, *,
               compute: bool = True) -> None:
    """The Sensitivity tab. ``solve(case_args)`` returns (count, result) for a variant case size.

    The toggle and settings table are always drawn so Streamlit keeps their values; the (possibly
    hundreds of) solves only run when ``compute`` is true, i.e. while the tab is open.
    """
    ss = st.session_state
    st.toggle("Run case size sensitivity", key="sens_on",
              help="Re-solve every combination of case-size changes: each dimension is unchanged or "
                   "moved by one of its own steps.")
    edited = st.data_editor(pd.DataFrame(ss.sens_config), key="sens_editor", hide_index=True, width="content",
                            column_config={**_SENS_EDITOR_COLUMNS, "Fixed step": {
                                **_SENS_EDITOR_COLUMNS["Fixed step"], "label": f"Fixed step ({unit})"}},
                            disabled=not ss.sens_on, num_rows="fixed")
    count = base[0]
    if not ss.sens_on or not compute:
        return
    if not count:
        st.info("No cases fit the base case, so there's nothing to compare against.")
        return
    config = edited.to_dict("records")
    st.caption(f"{_sens_variant_count(config, case_args, unit)} combinations: each dimension is "
               "either unchanged or moved by one of its steps.")
    bar = st.progress(0.0, text="Running sensitivity\u2026")
    rows, skipped = _sensitivity(
        solve, case_args, base, config, unit,
        progress=lambda done, total: bar.progress(done / total, text=f"Sensitivity: {done} of {total}"),
    )
    bar.empty()
    if len(rows) <= 1:
        st.info("Turn on at least one dimension above.")
        return
    _render_opportunities(rows, unit, max_weight, case_args["weight"])
    _render_sensitivity(rows)
    if skipped:
        st.caption("Skipped (a case dimension can't be zero or negative): " + "; ".join(skipped) + ".")
