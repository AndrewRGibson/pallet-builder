"""Session state: defaults, unit handling, presets, and mapping to and from .pallet documents."""

from __future__ import annotations

import streamlit as st

from pallet_builder import STANDARD_PALLETS, convert_length
from pallet_builder import inputs as input_files

# One unit system applies to every length and weight in the app.
UNIT_SYSTEMS = {"US (in, lb)": ("in", "lb"), "Metric (cm, kg)": ("cm", "kg")}
# Unit system names in .pallet files <-> the labels shown in the app.
FILE_UNITS = {"US": "US (in, lb)", "Metric": "Metric (cm, kg)"}
WEIGHT_UNITS = {"lb": 0.45359237, "kg": 1.0}  # kilograms per unit
# Typical max build heights (floor to top of load, including the pallet) applied with a preset.
DEFAULT_BUILD_HEIGHT = {"in": 60.0, "cm": 180.0}
LENGTH_KEYS = ("p_len", "p_wid", "p_deck", "p_height", "c_len", "c_wid", "c_hgt")
WEIGHT_KEYS = ("p_maxw", "c_weight")
CUSTOM = "Custom"
GA_STOP_FIXED, GA_STOP_STALL = "Fixed generations", "No improvement"
ALIGNMENT_LABELS = {
    "alternate": "Alternate sides (mirror across the deck)",
    "corner": "Flush to two sides (same corner)",
    "center": "Centred on the deck",
}
STACKING_LABELS = {
    "interlock": "Interlock when possible",
    "column": "Column (same pattern every layer)",
    "no_column": "No column stacking",
}
# Sensitivity settings.
DEFAULT_SENS_STEP = {"in": 0.2, "cm": 0.5}
DEFAULT_SENS_PCT = 2.0
SENS_FIXED, SENS_PCT = "Fixed", "Percent"
# (label, case_args key) for the dimensions analysed independently.
SENS_DIMENSIONS = (("Length", "length"), ("Width", "width"), ("Height", "height"))


def round6(value: float) -> float:
    return round(value, 6)


def units() -> tuple[str, str]:
    """The active (length unit, weight unit)."""
    return UNIT_SYSTEMS.get(st.session_state.get("units"), ("in", "lb"))


def sens_config() -> list[dict]:
    """The sensitivity settings with any pending edits from the settings table applied."""
    config = [dict(row) for row in st.session_state.sens_config]
    for index, changes in st.session_state.get("sens_editor", {}).get("edited_rows", {}).items():
        config[int(index)].update(changes)
    return config


def apply_preset() -> None:
    name = st.session_state.preset
    spec = STANDARD_PALLETS.get(name)
    if name == CUSTOM or spec is None:
        return
    length_unit, weight_unit = units()

    def length(key: str) -> float:
        return round6(convert_length(float(spec[key]), spec["unit"], length_unit))

    st.session_state.update(
        p_len=length("length"),
        p_wid=length("width"),
        p_deck=length("deck_height"),
        p_height=DEFAULT_BUILD_HEIGHT[length_unit],
        p_maxw=round6(float(spec["max_weight"]) * WEIGHT_UNITS[spec["weight_unit"]] / WEIGHT_UNITS[weight_unit]),
    )


def mark_custom() -> None:
    st.session_state.preset = CUSTOM


def convert_units() -> None:
    """Re-express every entered length and weight in the newly selected unit system."""
    old_length, old_weight = UNIT_SYSTEMS[st.session_state._units_prev]
    new_length, new_weight = units()

    def scale(key: str, factor: float) -> None:
        if st.session_state[key] is not None:  # blank = no limit
            st.session_state[key] = round6(st.session_state[key] * factor)

    factor = convert_length(1.0, old_length, new_length)
    for key in LENGTH_KEYS:
        scale(key, factor)
    scale("p_maxvol", factor**3)
    scale("p_maxarea", factor**2)
    for key in WEIGHT_KEYS:
        scale(key, WEIGHT_UNITS[old_weight] / WEIGHT_UNITS[new_weight])
    # Convert fixed sensitivity steps, keeping the round default (0.2 in / 0.5 cm) where unchanged.
    config = sens_config()
    for row in config:
        if abs(row["Fixed step"] - DEFAULT_SENS_STEP[old_length]) < 1e-9:
            row["Fixed step"] = DEFAULT_SENS_STEP[new_length]
        else:
            row["Fixed step"] = max(round(convert_length(row["Fixed step"], old_length, new_length), 2), 0.01)
    st.session_state.sens_config = config
    st.session_state.pop("sens_editor", None)  # the table restarts from the converted settings
    st.session_state._units_prev = st.session_state.units


def document_to_state(doc: dict) -> None:
    """Load a validated .pallet document into the app's inputs (all lengths/weights in its units)."""
    pallet, build, case, solve, sens = doc["pallet"], doc["build"], doc["case"], doc["solve"], doc["sensitivity"]
    ga = solve["ga"]
    unit_label = FILE_UNITS[doc["units"]]
    st.session_state.update(
        units=unit_label,
        _units_prev=unit_label,
        preset=pallet["preset"] if pallet["preset"] in STANDARD_PALLETS else CUSTOM,
        p_len=pallet["length"],
        p_wid=pallet["width"],
        p_deck=pallet["deck_height"],
        p_maxw=pallet["max_weight"],
        p_height=build["max_height"],
        p_maxvol=build["max_volume"],
        p_maxarea=build["max_plan_area"],
        c_len=case["length"],
        c_wid=case["width"],
        c_hgt=case["height"],
        c_weight=case["weight"],
        c_tsu=case["this_side_up"],
        stacking=solve["stacking"],
        alignment=solve["alignment"],
        min_support=solve["min_support_pct"],
        ga_on=ga["enabled"],
        ga_stop=GA_STOP_STALL if ga["stop_rule"] == "no_improvement" else GA_STOP_FIXED,
        ga_gens=ga["generations"],
        ga_stall=ga["stall"],
        ga_pop=ga["population"],
        ga_seed=ga["seed"],
        sens_on=sens["enabled"],
        sens_config=[
            {"Dimension": label, "On": dim["enabled"], "By": SENS_FIXED if dim["by"] == "fixed" else SENS_PCT,
             "Fixed step": dim["fixed_step"], "Percent step": dim["percent_step"], "Steps": dim["steps"]}
            for (label, _), dim in zip(SENS_DIMENSIONS,
                                       (sens["dimensions"][name] for name in input_files.SENS_DIMENSIONS))
        ],
        file_name=doc["name"],
        file_description=doc["description"],
    )
    st.session_state.pop("sens_editor", None)  # the settings table restarts from the loaded values


def state_to_document() -> dict:
    """The current inputs as a .pallet document."""
    ss = st.session_state
    doc = input_files.default_document()
    doc["name"] = ss.get("file_name", "")
    doc["description"] = ss.get("file_description", "")
    doc["units"] = next(name for name, label in FILE_UNITS.items() if label == ss.units)
    doc["pallet"] = {"preset": ss.preset, "length": ss.p_len, "width": ss.p_wid, "deck_height": ss.p_deck,
                     "max_weight": ss.p_maxw}
    doc["build"] = {"max_height": ss.p_height, "max_volume": ss.p_maxvol, "max_plan_area": ss.p_maxarea}
    doc["case"] = {"length": ss.c_len, "width": ss.c_wid, "height": ss.c_hgt, "weight": ss.c_weight,
                   "this_side_up": ss.c_tsu}
    doc["solve"] = {
        "stacking": ss.stacking,
        "alignment": ss.alignment,
        "min_support_pct": ss.min_support,
        "ga": {"enabled": ss.ga_on, "stop_rule": "no_improvement" if ss.ga_stop == GA_STOP_STALL else "fixed",
               "generations": ss.ga_gens, "stall": ss.ga_stall, "population": ss.ga_pop, "seed": ss.ga_seed},
    }
    doc["sensitivity"] = {
        "enabled": ss.sens_on,
        "dimensions": {
            name: {"enabled": bool(row["On"]), "by": "fixed" if row["By"] == SENS_FIXED else "percent",
                   "fixed_step": float(row["Fixed step"]), "percent_step": float(row["Percent step"]),
                   "steps": int(row["Steps"])}
            for name, row in zip(input_files.SENS_DIMENSIONS, sens_config())
        },
    }
    return doc


def reset_to_defaults() -> None:
    document_to_state(input_files.default_document())
    st.session_state.file_message = ("success", "Inputs reset to the defaults.")


def init_state() -> None:
    if "preset" in st.session_state:
        return
    # One source of defaults: the input file format's default document.
    document_to_state(input_files.default_document())
    st.session_state.update(file_name="", auto_solve=True, upload_nonce=0)


def preset_label(name: str) -> str:
    if name == CUSTOM:
        return CUSTOM
    spec = STANDARD_PALLETS[name]
    return f"{name} · {spec['length']:g}×{spec['width']:g} {spec['unit']}"


def solve_inputs() -> tuple[dict, dict, tuple | None, str, float, str]:
    """(pallet args, case args, GA settings, stacking, min support, alignment) from the current inputs."""
    ss = st.session_state
    length_unit, _ = units()
    ga = (ss.ga_gens, ss.ga_pop, ss.ga_seed, ss.ga_stall if ss.ga_stop == GA_STOP_STALL else 0) if ss.ga_on else None
    pallet_args = {
        "length": ss.p_len, "width": ss.p_wid, "height": ss.p_height, "unit": length_unit,
        "max_weight": ss.p_maxw, "max_volume": ss.p_maxvol, "max_plan_area": ss.p_maxarea,
        "deck_height": ss.p_deck, "name": None if ss.preset == CUSTOM else ss.preset,
    }
    case_args = {
        "name": "Case", "length": ss.c_len, "width": ss.c_wid, "height": ss.c_hgt, "weight": ss.c_weight,
        "unit": length_unit, "this_side_up": ss.c_tsu,
    }
    return pallet_args, case_args, ga, ss.stacking, ss.min_support / 100, ss.alignment
