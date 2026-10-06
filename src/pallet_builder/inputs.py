"""Pallet Builder input files (``.pallet``): save, load and validate a complete set of inputs.

A ``.pallet`` file is JSON. ``"format": "pallet-builder-input"`` marks it as ours and ``"version"``
lets the format evolve. Lengths and weights are in the file's own unit system (``"units"``: "US"
for in/lb or "Metric" for cm/kg). Any section or field left out falls back to the defaults, so a
hand-written file only needs the values that differ. An optional ``"expected"`` section records the
result a sample should produce (used by the test suite).
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

FILE_EXTENSION = ".pallet"
FORMAT = "pallet-builder-input"
VERSION = 1
UNITS = {"US": ("in", "lb"), "Metric": ("cm", "kg")}
STACKING = ("interlock", "column", "no_column")
ALIGNMENT = ("alternate", "corner", "center")
STOP_RULES = ("fixed", "no_improvement")
SENS_BY = ("fixed", "percent")
SENS_DIMENSIONS = ("length", "width", "height")

class InputFileError(ValueError):
    """Any problem with a .pallet file's content (bad JSON, wrong format, invalid or missing values)."""


_DEFAULT: dict[str, Any] = {
    "format": FORMAT,
    "version": VERSION,
    "name": "",
    "description": "",
    "units": "US",
    "pallet": {"preset": "CHEP", "length": 40.0, "width": 48.0, "deck_height": 6.0, "max_weight": 2200.0},
    "build": {"max_height": 60.0, "max_volume": None, "max_plan_area": None},
    "case": {"length": 12.0, "width": 10.0, "height": 8.0, "weight": 20.0, "this_side_up": True},
    "solve": {
        "stacking": "interlock",
        "alignment": "alternate",
        "min_support_pct": 70.0,
        "ga": {"enabled": True, "stop_rule": "fixed", "generations": 40, "stall": 25, "population": 24, "seed": 0},
    },
    "sensitivity": {
        "enabled": True,
        "dimensions": {
            name: {"enabled": True, "by": "fixed", "fixed_step": 0.2, "percent_step": 2.0, "steps": 1}
            for name in SENS_DIMENSIONS
        },
    },
}


def default_document() -> dict[str, Any]:
    return copy.deepcopy(_DEFAULT)


def _number(value: Any, where: str, *, minimum: float | None = None, allow_none: bool = False,
            integer: bool = False, maximum: float | None = None) -> float | int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputFileError(f"{where} must be a number{' or null' if allow_none else ''}, not {value!r}.")
    if integer and value != int(value):
        raise InputFileError(f"{where} must be a whole number, not {value!r}.")
    if minimum is not None and value < minimum:
        raise InputFileError(f"{where} must be at least {minimum:g}, not {value!r}.")
    if maximum is not None and value > maximum:
        raise InputFileError(f"{where} must be at most {maximum:g}, not {value!r}.")
    return int(value) if integer else float(value)


def _choice(value: Any, where: str, options: tuple[str, ...]) -> str:
    if value not in options:
        raise InputFileError(f"{where} must be one of {', '.join(options)}, not {value!r}.")
    return value


def _flag(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise InputFileError(f"{where} must be true or false, not {value!r}.")
    return value


def _merge(defaults: dict, given: Any, where: str) -> dict:
    if given is None:
        return copy.deepcopy(defaults)
    if not isinstance(given, dict):
        raise InputFileError(f"{where} must be an object, not {type(given).__name__}.")
    merged = copy.deepcopy(defaults)
    for key, value in given.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge(merged[key], value, f"{where}.{key}")
        else:
            merged[key] = value
    return merged


def validate_document(doc: Any) -> dict[str, Any]:
    """Check a parsed ``.pallet`` document, fill in defaults, and return the complete document.

    Raises ``InputFileError`` with the path of the first problem (e.g. ``case.length must be ...``).
    """
    if not isinstance(doc, dict):
        raise InputFileError("A .pallet file must contain a JSON object.")
    if doc.get("format") != FORMAT:
        raise InputFileError(f'Not a Pallet Builder input file (expected "format": "{FORMAT}").')
    version = doc.get("version", VERSION)
    if not isinstance(version, int) or version > VERSION:
        raise InputFileError(f"Unsupported file version {version!r}; this app reads version {VERSION} and earlier.")

    full = _merge(_DEFAULT, doc, "file")
    full["format"], full["version"] = FORMAT, VERSION
    for key in ("name", "description"):
        if not isinstance(full[key], str):
            raise InputFileError(f"{key} must be text.")
    _choice(full["units"], "units", tuple(UNITS))

    pallet = full["pallet"]
    if not isinstance(pallet["preset"], str):
        raise InputFileError("pallet.preset must be text (a standard pallet name or \"Custom\").")
    for key in ("length", "width", "deck_height"):
        pallet[key] = _number(pallet[key], f"pallet.{key}", minimum=0.001)
    pallet["max_weight"] = _number(pallet["max_weight"], "pallet.max_weight", minimum=0, allow_none=True)

    build = full["build"]
    for key in ("max_height", "max_volume", "max_plan_area"):
        build[key] = _number(build[key], f"build.{key}", minimum=0, allow_none=True)
    if build["max_height"] is not None and build["max_height"] <= pallet["deck_height"]:
        raise InputFileError("build.max_height must be greater than pallet.deck_height (it includes the pallet).")

    case = full["case"]
    for key in ("length", "width", "height"):
        case[key] = _number(case[key], f"case.{key}", minimum=0.001)
    case["weight"] = _number(case["weight"], "case.weight", minimum=0)
    case["this_side_up"] = _flag(case["this_side_up"], "case.this_side_up")

    solve = full["solve"]
    _choice(solve["stacking"], "solve.stacking", STACKING)
    _choice(solve["alignment"], "solve.alignment", ALIGNMENT)
    solve["min_support_pct"] = _number(solve["min_support_pct"], "solve.min_support_pct", minimum=0, maximum=100)
    ga = solve["ga"]
    ga["enabled"] = _flag(ga["enabled"], "solve.ga.enabled")
    _choice(ga["stop_rule"], "solve.ga.stop_rule", STOP_RULES)
    ga["generations"] = _number(ga["generations"], "solve.ga.generations", minimum=1, maximum=2000, integer=True)
    ga["stall"] = _number(ga["stall"], "solve.ga.stall", minimum=1, maximum=500, integer=True)
    ga["population"] = _number(ga["population"], "solve.ga.population", minimum=4, maximum=200, integer=True)
    ga["seed"] = _number(ga["seed"], "solve.ga.seed", minimum=0, integer=True)

    sens = full["sensitivity"]
    sens["enabled"] = _flag(sens["enabled"], "sensitivity.enabled")
    for name in SENS_DIMENSIONS:
        dim = sens["dimensions"][name]
        where = f"sensitivity.dimensions.{name}"
        dim["enabled"] = _flag(dim["enabled"], f"{where}.enabled")
        _choice(dim["by"], f"{where}.by", SENS_BY)
        dim["fixed_step"] = round(_number(dim["fixed_step"], f"{where}.fixed_step", minimum=0.01), 2)
        dim["percent_step"] = _number(dim["percent_step"], f"{where}.percent_step", minimum=0.1, maximum=50)
        dim["steps"] = _number(dim["steps"], f"{where}.steps", minimum=1, maximum=3, integer=True)
    return full


def loads(text: str) -> dict[str, Any]:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputFileError(f"Not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno}).") from exc
    return validate_document(doc)


def load(path: str | Path) -> dict[str, Any]:
    return loads(Path(path).read_text(encoding="utf-8"))


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(validate_document(doc), indent=2) + "\n"


def sample_paths(directory: str | Path) -> list[Path]:
    return sorted(Path(directory).glob(f"*{FILE_EXTENSION}"))


def solver_arguments(doc: dict[str, Any]) -> tuple[dict, dict, dict]:
    """(Pallet kwargs, Case kwargs, solve options) for ``maximize_case_count`` from a document."""
    doc = validate_document(doc)
    length_unit, _ = UNITS[doc["units"]]
    pallet, build, case, solve = doc["pallet"], doc["build"], doc["case"], doc["solve"]
    ga = solve["ga"]
    pallet_kwargs = {
        "length": pallet["length"], "width": pallet["width"], "height": build["max_height"], "unit": length_unit,
        "max_weight": pallet["max_weight"], "max_volume": build["max_volume"],
        "max_plan_area": build["max_plan_area"], "deck_height": pallet["deck_height"],
        "name": None if pallet["preset"] == "Custom" else pallet["preset"],
    }
    case_kwargs = {
        "name": "Case", "length": case["length"], "width": case["width"], "height": case["height"],
        "weight": case["weight"], "unit": length_unit, "this_side_up": case["this_side_up"],
    }
    options = {
        "optimize": ga["enabled"], "optimization_generations": ga["generations"],
        "optimization_population": ga["population"], "optimization_seed": ga["seed"],
        "optimization_stall": ga["stall"] if ga["stop_rule"] == "no_improvement" else 0,
        "stacking": solve["stacking"], "min_support": solve["min_support_pct"] / 100,
        "alignment": solve["alignment"],
    }
    return pallet_kwargs, case_kwargs, options
