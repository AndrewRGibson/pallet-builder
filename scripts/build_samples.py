"""Rebuild samples/*.pallet, recording each one's solved result (and the facts its description claims)
as "expected". tests/test_inputs.py checks every sample against these, so a description can't drift
from what the solver actually does.

Run from the repo root:  uv run python scripts/build_samples.py
"""

from __future__ import annotations

from pathlib import Path

from pallet_builder import Case, Pallet, maximize_case_count
from pallet_builder.inputs import (
    default_document,
    dumps,
    solver_arguments,
    validate_document,
)

OUT = Path(__file__).resolve().parents[1] / "samples"


def doc(name, description, units="US", pallet=None, build=None, case=None, solve=None, sens_step=None):
    d = default_document()
    d["name"], d["description"], d["units"] = name, description, units
    d["pallet"].update(pallet or {})
    d["build"].update(build or {})
    d["case"].update(case or {})
    for key, value in (solve or {}).items():
        if key == "ga":
            d["solve"]["ga"].update(value)
        else:
            d["solve"][key] = value
    if sens_step is not None:
        for dim in d["sensitivity"]["dimensions"].values():
            dim["fixed_step"] = sens_step
    return d


EUR = {"preset": "EUR_1200X800", "length": 120.0, "width": 80.0, "deck_height": 14.4, "max_weight": 1500.0}
CUSTOM = {"preset": "Custom", "length": 40.0, "width": 48.0, "deck_height": 6.0, "max_weight": None}

SAMPLES = {
    "01-chep-default": doc(
        "CHEP, 12 x 10 x 8 in cases",
        "The app's default: a CHEP pallet built to 60 in. Every layer is a full 16-case grid (flipping it changes "
        "nothing, so the layers stack in columns), and space limits the load."),
    "02-chep-exact-tile-8x5": doc(
        "CHEP, 8 x 5 x 6 in cases (exact tile, interlocked)",
        "8 x 5 cases tile the 40 x 48 deck exactly: 48 per layer, nine layers. The block packer's uniform grid would "
        "stack in columns; the GA finds an equally full pattern mixing both orientations that interlocks fully when "
        "every other layer is mirrored.",
        case={"length": 8.0, "width": 5.0, "height": 6.0, "weight": 4.0}),
    "03-chep-ga-interlock-9x7": doc(
        "CHEP, 9 x 7 x 8 in cases (GA beats block packer, interlocked)",
        "The block packer finds 27 per layer; the GA finds 28, in a pattern that interlocks when every other layer "
        "is turned 180 degrees.",
        case={"length": 9.0, "width": 7.0, "height": 8.0, "weight": 5.0}),
    "04-chep-no-column-9x8": doc(
        "CHEP, 9 x 8 x 8 in cases (no column stacking)",
        "Column stacking is disallowed but no pattern interlocks with 70% support, so the load is limited to one "
        "layer.",
        case={"length": 9.0, "width": 8.0, "height": 8.0, "weight": 5.0}, solve={"stacking": "no_column"}),
    "05-chep-weight-limited": doc(
        "CHEP, heavy 12 x 10 x 8 in cases (weight-limited)",
        "40 lb cases: the 2,200 lb rating caps the load at 55 cases, well below the 96 the space would hold.",
        case={"weight": 40.0}),
    "06-tipping-tall-case": doc(
        "Custom 40 x 48 in, tall 10 x 10 x 30 in case laid on its side",
        "Upright the case is taller than the 20 in above the deck; with tipping allowed it lies down in two 10 in "
        "layers.",
        pallet=CUSTOM, build={"max_height": 26.0},
        case={"length": 10.0, "width": 10.0, "height": 30.0, "weight": 10.0, "this_side_up": False}),
    "07-rotated-footprint-45x10": doc(
        "Custom 40 x 48 in, 45 x 10 x 5 in case (fits only rotated)",
        "The case is longer than the deck one way, so it only fits turned 90 degrees: one layer of 4 (no build "
        "height is set, so the load is a single layer).",
        pallet=CUSTOM, build={"max_height": None},
        case={"length": 45.0, "width": 10.0, "height": 5.0, "weight": 10.0}),
    "08-eur-metric": doc(
        "EUR 1200 x 800 mm, 30 x 20 x 15 cm cases (metric)",
        "A metric example: a EUR pallet built to 180 cm with 8 kg cases. Space limits the load to 11 layers of 16, "
        "and the layers interlock.",
        units="Metric", pallet=EUR, build={"max_height": 180.0},
        case={"length": 30.0, "width": 20.0, "height": 15.0, "weight": 8.0}, sens_step=0.5),
    "09-too-tall-infeasible": doc(
        "CHEP built to 12 in, 8 in tall cases (infeasible)",
        "Only 6 in remain above the 6 in deck, so no 8 in case fits; the app explains why.",
        build={"max_height": 12.0}),
    "10-column-19x7-bound": doc(
        "CHEP, 19 x 7 x 8 in cases (column stacking, GA reaches the bound)",
        "With column stacking the GA's objective is the case count alone. The block packer finds 13 per layer; the "
        "GA reaches the bound of 14 (deck area / case footprint).",
        case={"length": 19.0, "width": 7.0, "height": 8.0, "weight": 5.0}, solve={"stacking": "column"}),
}


def facts(pallet: Pallet, case_kwargs: dict, count: int, result) -> dict:
    """The checkable claims behind a sample's description."""
    selected = next((run.solver for run in result.solver_runs if run.selected), None)
    weight_cap = (int(pallet.max_weight // case_kwargs["weight"])
                  if pallet.max_weight is not None and case_kwargs["weight"] > 0 else None)
    if not count:
        limited_by = "infeasible"
    elif count == result.capacity:
        limited_by = "space"
    elif weight_cap == count:
        limited_by = "weight"
    else:
        limited_by = "other"
    base_layer = [p for p in result.placements if p.z == 0]
    return {
        "cases": count,
        "layers": result.layers,
        "cases_per_layer": result.cases_per_layer,
        "selected_solver": selected,
        "interlocked": result.interlock > 0,
        "limited_by": limited_by,
        "mixed_orientations": len({(round(p.length, 6), round(p.width, 6)) for p in base_layer}) > 1,
        "tipped": any(p.orientation[2] != 2 for p in result.placements),
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for stale in OUT.glob("*.pallet"):
        stale.unlink()
    for stem, sample in SAMPLES.items():
        sample = validate_document(sample)
        pallet_kwargs, case_kwargs, options = solver_arguments(sample)
        pallet = Pallet(**pallet_kwargs)
        count, result = maximize_case_count(pallet, Case(**case_kwargs), **options)
        sample["expected"] = facts(pallet, case_kwargs, count, result)
        (OUT / f"{stem}.pallet").write_text(dumps(sample), encoding="utf-8", newline="\n")
        print(f"{stem}: {sample['expected']}")


if __name__ == "__main__":
    main()
