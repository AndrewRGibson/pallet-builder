"""Running the solver (cached) and explaining its result."""

from __future__ import annotations

import time
from dataclasses import dataclass

import streamlit as st

from pallet_builder import Case, Pallet, maximize_case_count, solve_pallet_layout


@st.cache_data(show_spinner=False, max_entries=256)
def _solve_cached(pallet_args: dict, case_args: dict, ga: tuple | None, stacking: str, min_support: float):
    started = time.perf_counter()
    pallet = Pallet(**pallet_args)
    case = Case(**case_args)
    options = {"optimize": ga is not None, "stacking": stacking, "min_support": min_support}
    if ga is not None:
        options.update(optimization_generations=ga[0], optimization_population=ga[1], optimization_seed=ga[2],
                       optimization_stall=ga[3])
    count, result = maximize_case_count(pallet, case, **options)
    # Re-solve one more case to explain what stops the count going higher.
    limit = (
        solve_pallet_layout(pallet, [Case(**{**case_args, "quantity": count + 1})], **options).violations
        if count else []
    )
    return count, result, limit, (time.perf_counter() - started) * 1000


@dataclass(frozen=True)
class Solved:
    count: int
    result: object
    limit_violations: list[str]
    solve_ms: float  # time the solve took when it was computed
    cached: bool  # True when this call reused an earlier result


def solve(pallet_args: dict, case_args: dict, ga: tuple | None, stacking: str, min_support: float) -> Solved:
    started = time.perf_counter()
    count, result, limit, solve_ms = _solve_cached(pallet_args, case_args, ga, stacking, min_support)
    wall_ms = (time.perf_counter() - started) * 1000
    # A cache hit returns in a fraction of the original solve time.
    return Solved(count, result, limit, solve_ms, cached=wall_ms < 0.5 * solve_ms)


def summarize_violations(violations: list[str]) -> list[str]:
    """Collapse the per-case "no footprint" messages into one line."""
    no_room = [v for v in violations if v.startswith("No feasible footprint")]
    summary = [v for v in violations if v not in no_room]
    if no_room:
        summary.append(f"{len(no_room)} case(s) had no room left on the pallet.")
    return summary


def limit_reason(violations: list[str]) -> str:
    text = " ".join(violations).lower()
    if "weight" in text:
        return "max weight"
    if "volume" in text:
        return "max volume"
    if "plan area" in text:
        return "max plan area"
    return "pallet space"


def limit_text(solved: Solved, pallet: Pallet) -> str:
    """One line saying what limits the count (empty when nothing fits)."""
    result = solved.result
    if not solved.count:
        return ""
    if solved.count == result.capacity:
        if pallet.height is None:
            return "single layer (set a max build height to stack layers)"
        return f"limited by pallet space ({result.max_layers} layers of {result.cases_per_layer} fill the build height)"
    if solved.limit_violations:
        return f"limited by {limit_reason(solved.limit_violations)}"
    return ""


def solver_notes(result, case_args: dict) -> list[str]:
    """Things the user should know about how this result was found (solver limits that applied)."""
    notes = []
    for run in result.solver_runs:
        if run.solver == "Block packer" and "two-block patterns" in run.note:
            notes.append(f"{run.family}: the deck is large relative to the case, so the block packer was limited "
                         "to two-block patterns; denser layouts may exist.")
        if run.solver.startswith("Genetic") and not run.ran and "exceeds the GA limit" in run.note:
            notes.append(f"{run.family}: the GA was skipped because a layer would hold over 150 cases; "
                         "the layer comes from the block packer alone.")
        if run.solver.startswith("Genetic") and run.ran and "generation limit" in run.note \
                and run.cases_per_layer < run.target:
            notes.append(f"{run.family}: the GA stopped at its generation limit below the bound; more generations, "
                         "a larger population or the \"No improvement\" stop rule may find more.")
    if not case_args["this_side_up"]:
        notes.append("Tipping is allowed, but every case in the load uses the same upright side (so layers are flat).")
    notes.append("Each layer uses one pattern (with every other layer flipped when interlocking); layers with two "
                 "different patterns aren't considered.")
    return notes
