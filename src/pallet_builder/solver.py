from __future__ import annotations

import random
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from itertools import permutations

_UNIT_TO_METERS = {
    "mm": 0.001,
    "cm": 0.01,
    "m": 1.0,
    "in": 0.0254,
    "inch": 0.0254,
    "inches": 0.0254,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
    "yd": 0.9144,
    "yard": 0.9144,
}

# max_weight is expressed in weight_unit; Pallet itself is unit-agnostic about weight.
_STANDARD_PALLETS = {
    "CHEP": {"length": 40, "width": 48, "deck_height": 6, "max_weight": 2200, "weight_unit": "lb", "unit": "in"},
    "GMA": {"length": 40, "width": 48, "deck_height": 6, "max_weight": 2200, "weight_unit": "lb", "unit": "in"},
    "EUR_1200X800": {"length": 1200, "width": 800, "deck_height": 144, "max_weight": 1500, "weight_unit": "kg", "unit": "mm"},
    "EUR_1000X1200": {"length": 1000, "width": 1200, "deck_height": 144, "max_weight": 1500, "weight_unit": "kg", "unit": "mm"},
}
_STANDARD_PALLET_ALIASES = {"EURO": "EUR_1200X800"}
STANDARD_PALLETS = _STANDARD_PALLETS


def normalize_unit(unit: str) -> str:
    if unit is None:
        raise ValueError("Unit is required.")
    normalized = str(unit).strip().lower().replace(" ", "")
    aliases = {
        "mm": "mm",
        "millimeter": "mm",
        "millimetre": "mm",
        "centimeter": "cm",
        "centimetre": "cm",
        "cm": "cm",
        "meter": "m",
        "metre": "m",
        "m": "m",
        "in": "in",
        "inch": "in",
        "inches": "in",
        "ft": "ft",
        "foot": "ft",
        "feet": "ft",
        "yd": "yd",
        "yard": "yd",
    }
    if normalized not in aliases:
        raise ValueError(f"Unsupported unit {unit!r}.")
    return aliases[normalized]


def convert_length(value: float, from_unit: str, to_unit: str) -> float:
    from_unit = normalize_unit(from_unit)
    to_unit = normalize_unit(to_unit)
    if from_unit == to_unit:
        return float(value)
    value_in_meters = float(value) * _UNIT_TO_METERS[from_unit]
    return value_in_meters / _UNIT_TO_METERS[to_unit]


@dataclass(frozen=True)
class Case:
    """Represents a case with a fixed box geometry and optional unit metadata."""

    name: str
    length: float
    width: float
    height: float
    weight: float = 0.0
    quantity: int = 1
    unit: str = "in"
    this_side_up: bool = True

    def __post_init__(self) -> None:
        if self.length <= 0 or self.width <= 0 or self.height <= 0:
            raise ValueError(f"Case dimensions for {self.name!r} must all be positive.")
        if self.quantity <= 0:
            raise ValueError(f"Case quantity for {self.name!r} must be positive.")
        if self.weight < 0:
            raise ValueError(f"Case weight for {self.name!r} cannot be negative.")
        normalize_unit(self.unit)

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height

    @property
    def footprint_area(self) -> float:
        return self.length * self.width

    def oriented_dimensions(self, orientation: tuple[int, int, int]) -> tuple[float, float, float]:
        axes = [self.length, self.width, self.height]
        return tuple(axes[i] for i in orientation)


@dataclass
class Pallet:
    """Physical pallet envelope and operational constraints.

    ``height`` is the maximum load height above the deck (``None`` means no limit).
    ``deck_height`` is the pallet's own height and is informational only.
    """

    length: float
    width: float
    height: float | None = None
    unit: str = "in"
    max_weight: float | None = None
    max_volume: float | None = None
    max_plan_area: float | None = None
    name: str | None = None
    deck_height: float | None = None

    def __post_init__(self) -> None:
        if self.length <= 0 or self.width <= 0:
            raise ValueError("Pallet length and width must be positive.")
        if self.height is not None and self.height <= 0:
            raise ValueError("Pallet max load height must be positive when provided.")
        if self.deck_height is not None and self.deck_height <= 0:
            raise ValueError("Pallet deck height must be positive when provided.")
        normalize_unit(self.unit)

    @classmethod
    def from_standard(cls, name: str, *, unit: str = "in", max_load_height: float | None = None) -> Pallet:
        key = str(name).upper()
        key = _STANDARD_PALLET_ALIASES.get(key, key)
        if key not in _STANDARD_PALLETS:
            available = ", ".join(sorted(_STANDARD_PALLETS))
            raise ValueError(f"Unknown standard pallet {name!r}. Available: {available}")
        spec = _STANDARD_PALLETS[key]
        length = convert_length(float(spec["length"]), spec["unit"], unit)
        width = convert_length(float(spec["width"]), spec["unit"], unit)
        deck_height = convert_length(float(spec["deck_height"]), spec["unit"], unit)
        max_weight = float(spec["max_weight"])
        return cls(
            length=length,
            width=width,
            height=max_load_height,
            unit=unit,
            max_weight=max_weight,
            name=name,
            deck_height=deck_height,
        )

    @property
    def plan_area(self) -> float:
        return self.length * self.width


@dataclass
class Placement:
    case_name: str
    x: float
    y: float
    z: float
    length: float
    width: float
    height: float
    orientation: tuple[int, int, int]


@dataclass
class LayoutResult:
    placements: list[Placement]
    total_weight: float
    utilization: float
    overhang: float
    underhang: float
    feasible: bool
    violations: list[str] = field(default_factory=list)


def _orientations_for(case: Case) -> list[tuple[int, int, int]]:
    """Orientations as (footprint length axis, footprint width axis, vertical axis).

    A "this side up" case may only spin flat on the deck; otherwise it may also be tipped.
    """
    if case.this_side_up:
        return [(0, 1, 2), (1, 0, 2)]
    return sorted(permutations(range(3)))


def _case_in_unit(case: Case, unit: str) -> Case:
    if normalize_unit(case.unit) == normalize_unit(unit):
        return case
    return replace(
        case,
        length=convert_length(case.length, case.unit, unit),
        width=convert_length(case.width, case.unit, unit),
        height=convert_length(case.height, case.unit, unit),
        unit=unit,
    )


def _coerce_case(item: Case | dict[str, float | str | int], unit: str) -> Case:
    """Accept a Case or a plain dict and return a Case expressed in ``unit``."""
    if not isinstance(item, Case):
        item = Case(
            name=str(item["name"]),
            length=float(item["length"]),
            width=float(item["width"]),
            height=float(item["height"]),
            weight=float(item.get("weight", 0.0)),
            quantity=int(item.get("quantity", 1)),
            unit=str(item.get("unit", unit)),
            this_side_up=bool(item.get("this_side_up", True)),
        )
    return _case_in_unit(item, unit)


def _fits_footprint(case: Case, pallet: Pallet) -> bool:
    for orientation in _orientations_for(case):
        length, width, _ = case.oriented_dimensions(orientation)
        if length <= pallet.length and width <= pallet.width:
            return True
    return False


def _expand_case_quantities(cases: Iterable[Case]) -> list[Case]:
    expanded: list[Case] = []
    for case in cases:
        for index in range(case.quantity):
            expanded.append(replace(case, name=f"{case.name}-{index + 1}", quantity=1))
    return expanded


def _split_free_rectangles(
    free_rectangles: list[tuple[float, float, float, float]],
    x: float,
    y: float,
    width: float,
    height: float,
) -> list[tuple[float, float, float, float]]:
    updated: list[tuple[float, float, float, float]] = []
    for rect_x, rect_y, rect_w, rect_h in free_rectangles:
        if x >= rect_x + rect_w or x + width <= rect_x or y >= rect_y + rect_h or y + height <= rect_y:
            updated.append((rect_x, rect_y, rect_w, rect_h))
            continue

        if x > rect_x:
            updated.append((rect_x, rect_y, x - rect_x, rect_h))
        if x + width < rect_x + rect_w:
            updated.append((x + width, rect_y, rect_x + rect_w - (x + width), rect_h))
        if y > rect_y:
            updated.append((rect_x, rect_y, rect_w, y - rect_y))
        if y + height < rect_y + rect_h:
            updated.append((rect_x, y + height, rect_w, rect_y + rect_h - (y + height)))

    deduped: list[tuple[float, float, float, float]] = []
    for candidate in sorted(updated, key=lambda item: (item[2] * item[3], item[0], item[1])):
        if candidate[2] > 1e-9 and candidate[3] > 1e-9 and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _candidate_positions(
    case: Case,
    free_rectangles: Sequence[tuple[float, float, float, float]],
    max_height: float | None = None,
) -> list[tuple[float, float, float, float, tuple[int, int, int]]]:
    orientations = _orientations_for(case)
    if max_height is not None:
        # Prefer orientations under the height limit; if none of them can be placed, fall back to
        # all orientations so the height check reports the real reason instead of a footprint error.
        within_height = [o for o in orientations if case.oriented_dimensions(o)[2] <= max_height + 1e-9]
        positions = _positions_for_orientations(case, within_height, free_rectangles)
        if positions:
            return positions
    return _positions_for_orientations(case, orientations, free_rectangles)


def _positions_for_orientations(
    case: Case,
    orientations: Sequence[tuple[int, int, int]],
    free_rectangles: Sequence[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float, tuple[int, int, int]]]:
    positions: list[tuple[float, float, float, float, tuple[int, int, int]]] = []
    for orientation in orientations:
        length, width, _ = case.oriented_dimensions(orientation)
        for rect_x, rect_y, rect_w, rect_h in free_rectangles:
            if length <= rect_w and width <= rect_h:
                positions.append((rect_x, rect_y, length, width, orientation))
    positions.sort(key=lambda item: (item[2] * item[3], item[0], item[1]))
    return positions


# Above this many (x, y) normal-position states the recursive guillotine search gets slow in pure
# Python, so the block packer falls back to one-cut (two-block) patterns.
_MAX_GUILLOTINE_STATES = 6000
_UNLIMITED_CUTS = -1
_GREEDY_FALLBACK_MAX_CASES = 400


def _normal_positions(limit: float, sizes: Sequence[float]) -> list[float]:
    """All offsets reachable as non-negative integer combinations of ``sizes`` (normal patterns)."""
    positions = {0.0}
    frontier = [0.0]
    while frontier:
        start = frontier.pop()
        for size in sizes:
            nxt = round(start + size, 9)
            if nxt <= limit + 1e-9 and nxt not in positions:
                positions.add(nxt)
                frontier.append(nxt)
    return sorted(positions)


@lru_cache(maxsize=64)
def _block_layout(
    length: float,
    width: float,
    footprints: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float, int], ...]:
    """Best guillotine layout of identical rectangles, as (x, y, footprint index) tuples.

    Each region is either filled with a uniform grid of one footprint or cut in two at a normal
    position and both halves solved recursively. This finds the classic block patterns (e.g. a
    5x8 case on a 40x48 deck: 48, where the greedy packer manages 45).
    """
    xs = _normal_positions(length, [fp[0] for fp in footprints])
    ys = _normal_positions(width, [fp[1] for fp in footprints])
    max_cuts = _UNLIMITED_CUTS if len(xs) * len(ys) <= _MAX_GUILLOTINE_STATES else 1
    memo: dict[tuple[float, float, int], tuple[int, tuple]] = {}

    def snap(value: float, positions: list[float]) -> float:
        # A region's best layout only depends on the largest normal size that fits inside it.
        return positions[bisect_right(positions, value + 1e-9) - 1]

    def solve(region_l: float, region_w: float, cuts: int) -> tuple[int, tuple]:
        region_l, region_w = snap(region_l, xs), snap(region_w, ys)
        key = (region_l, region_w, cuts)
        if key in memo:
            return memo[key]

        best: tuple[int, tuple] = (0, ("empty",))
        for index, (fp_l, fp_w) in enumerate(footprints):
            count = int((region_l + 1e-9) // fp_l) * int((region_w + 1e-9) // fp_w)
            if count > best[0]:
                best = (count, ("grid", index))

        if cuts != 0:
            sub_cuts = cuts if cuts == _UNLIMITED_CUTS else cuts - 1
            for x in xs:
                if x >= region_l - 1e-9:
                    break
                if x > 0:
                    count = solve(x, region_w, sub_cuts)[0] + solve(region_l - x, region_w, sub_cuts)[0]
                    if count > best[0]:
                        best = (count, ("v", x, sub_cuts))
            for y in ys:
                if y >= region_w - 1e-9:
                    break
                if y > 0:
                    count = solve(region_l, y, sub_cuts)[0] + solve(region_l, region_w - y, sub_cuts)[0]
                    if count > best[0]:
                        best = (count, ("h", y, sub_cuts))

        memo[key] = best
        return best

    spots: list[tuple[float, float, int]] = []

    def build(x0: float, y0: float, region_l: float, region_w: float, cuts: int) -> None:
        _, plan = solve(region_l, region_w, cuts)
        if plan[0] == "grid":
            fp_l, fp_w = footprints[plan[1]]
            for i in range(int((region_l + 1e-9) // fp_l)):
                for j in range(int((region_w + 1e-9) // fp_w)):
                    spots.append((round(x0 + i * fp_l, 9), round(y0 + j * fp_w, 9), plan[1]))
        elif plan[0] == "v":
            build(x0, y0, plan[1], region_w, plan[2])
            build(x0 + plan[1], y0, region_l - plan[1], region_w, plan[2])
        elif plan[0] == "h":
            build(x0, y0, region_l, plan[1], plan[2])
            build(x0, y0 + plan[1], region_l, region_w - plan[1], plan[2])

    build(0.0, 0.0, length, width, max_cuts)
    # Fill from the origin outward so a partial load (fewer cases than fit) stays compact.
    return tuple(sorted(spots, key=lambda spot: (spot[1], spot[0])))


def _pack_single_type(pallet: Pallet, cases: Sequence[Case]) -> tuple[list[Placement], float, list[str]]:
    case = cases[0]
    orientations = _orientations_for(case)
    within_height = orientations
    if pallet.height is not None:
        within_height = [o for o in orientations if case.oriented_dimensions(o)[2] <= pallet.height + 1e-9]

    spots: tuple[tuple[float, float, int], ...] = ()
    # Prefer orientations under the height limit; if none of them fit, fall back to all of them so
    # the height check reports the real reason instead of a footprint error.
    for candidates in (within_height, orientations):
        footprints: list[tuple[float, float]] = []
        footprint_orientations: list[tuple[int, int, int]] = []
        for orientation in candidates:
            length, width, _ = case.oriented_dimensions(orientation)
            footprint = (round(length, 9), round(width, 9))
            if footprint not in footprints:
                footprints.append(footprint)
                footprint_orientations.append(orientation)
        if footprints:
            spots = _block_layout(round(pallet.length, 9), round(pallet.width, 9), tuple(footprints))
        if spots:
            break

    placements = []
    for (x, y, index), item in zip(spots, cases):
        orientation = footprint_orientations[index]
        length, width, height = item.oriented_dimensions(orientation)
        placements.append(Placement(item.name, x, y, 0.0, length, width, height, orientation))

    if not placements:
        return [], 0.0, ["No cases could be placed on the pallet."]
    violations = [f"No feasible footprint for case {item.name!r} on the pallet." for item in cases[len(placements):]]
    used_area = sum(placement.length * placement.width for placement in placements)
    return placements, used_area / pallet.plan_area, violations


def _pack_layer(pallet: Pallet, cases: Sequence[Case]) -> tuple[list[Placement], float, list[str]]:
    if cases and _single_case_type(cases):
        block = _pack_single_type(pallet, cases)
        # The greedy packer can occasionally find a non-guillotine layout that beats the block
        # packer, but it is O(n^2), so only try it on modest loads.
        if len(block[0]) == len(cases) or len(cases) > _GREEDY_FALLBACK_MAX_CASES:
            return block
        greedy = _pack_greedy(pallet, cases)
        return greedy if len(greedy[0]) > len(block[0]) else block
    return _pack_greedy(pallet, cases)


def _pack_greedy(pallet: Pallet, cases: Sequence[Case]) -> tuple[list[Placement], float, list[str]]:
    free_rectangles: list[tuple[float, float, float, float]] = [(0.0, 0.0, pallet.length, pallet.width)]
    placements: list[Placement] = []
    used_area = 0.0
    violations: list[str] = []

    for case in sorted(cases, key=lambda item: (item.length * item.width, max(item.length, item.width), item.height), reverse=True):
        candidate: tuple[float, float, float, float, tuple[int, int, int]] | None = None
        for position in _candidate_positions(case, free_rectangles, pallet.height):
            x, y, length, width, orientation = position
            if candidate is None or (length * width) > (candidate[2] * candidate[3]):
                candidate = (x, y, length, width, orientation)
        if candidate is None:
            violations.append(f"No feasible footprint for case {case.name!r} on the pallet.")
            continue

        x, y, length, width, orientation = candidate
        placements.append(
            Placement(
                case_name=case.name,
                x=x,
                y=y,
                z=0.0,
                length=length,
                width=width,
                height=case.oriented_dimensions(orientation)[2],
                orientation=orientation,
            )
        )
        used_area += length * width
        free_rectangles = _split_free_rectangles(free_rectangles, x, y, length, width)

    if not placements:
        return [], 0.0, ["No cases could be placed on the pallet."]

    return placements, used_area / pallet.plan_area, violations


def _score_layout_result(pallet: Pallet, result: LayoutResult) -> float:
    if not result.feasible:
        return -1_000_000.0 - 100.0 * len(result.violations) - 0.001 * result.overhang - 0.001 * result.underhang
    score = result.utilization
    score -= 0.001 * result.overhang
    score -= 0.001 * result.underhang
    return score


def maximize_case_count(
    pallet: Pallet,
    case: Case | dict[str, float | str | int],
    *,
    progress_callback: callable | None = None,
) -> tuple[int, LayoutResult]:
    """Return the maximum number of identical cases that fit on a pallet.

    The function uses a binary search over the feasible count and returns both the count and the
    final layout that achieves that maximum. A progress callback may be passed to report iteration
    progress during the search.
    """

    case = _coerce_case(case, pallet.unit)

    if not _fits_footprint(case, pallet):
        return 0, LayoutResult([], 0.0, 0.0, 0.0, 0.0, False, ["Case footprint exceeds pallet footprint in every allowed orientation."])

    if case.quantity <= 0:
        raise ValueError("Case quantity must be positive for max-case search.")

    min_footprint = min(
        case.oriented_dimensions(orientation)[0] * case.oriented_dimensions(orientation)[1]
        for orientation in _orientations_for(case)
    )
    upper_bound = int(pallet.plan_area // min_footprint)
    if pallet.max_weight is not None and case.weight > 0:
        upper_bound = min(upper_bound, int(pallet.max_weight // case.weight))
    if pallet.max_plan_area is not None:
        upper_bound = min(upper_bound, int(pallet.max_plan_area // min_footprint))
    if pallet.max_volume is not None:
        upper_bound = min(upper_bound, int(pallet.max_volume // case.volume))

    if upper_bound <= 0:
        # Solve a single case so the caller sees which limit (weight, volume, area) rules it out.
        _, explanation = _explain_single_case(pallet, case)
        return 0, explanation

    lower_bound = 1
    best_count = 0
    best_result = LayoutResult([], 0.0, 0.0, 0.0, 0.0, False, ["No cases fit."])
    iterations = 0

    while lower_bound <= upper_bound:
        iterations += 1
        mid = (lower_bound + upper_bound) // 2
        result = solve_pallet_layout(pallet, [replace(case, quantity=mid)])

        if progress_callback is not None:
            progress_callback(iterations, lower_bound, upper_bound, mid, result)

        if result.feasible and len(result.placements) == mid:
            best_count = mid
            best_result = result
            lower_bound = mid + 1
        else:
            upper_bound = mid - 1

    if best_count == 0:
        _, explanation = _explain_single_case(pallet, case)
        return 0, explanation

    return best_count, best_result


def _explain_single_case(pallet: Pallet, case: Case) -> tuple[int, LayoutResult]:
    result = solve_pallet_layout(pallet, [replace(case, quantity=1)])
    violations = result.violations or ["No cases fit on this pallet."]
    return 0, LayoutResult([], 0.0, 0.0, 0.0, 0.0, False, violations)


def _single_case_type(cases: Sequence[Case]) -> bool:
    if not cases:
        return True
    signature = (cases[0].length, cases[0].width, cases[0].height)
    return all((case.length, case.width, case.height) == signature for case in cases[1:])


def _evaluate_case_order(
    pallet: Pallet,
    cases: Sequence[Case],
) -> tuple[float, LayoutResult]:
    placements, utilization, packing_violations = _pack_layer(pallet, cases)
    violations: list[str] = list(packing_violations)

    overhang = 0.0
    for placement in placements:
        if placement.x + placement.length > pallet.length + 1e-9:
            overhang += placement.x + placement.length - pallet.length
        if placement.y + placement.width > pallet.width + 1e-9:
            overhang += placement.y + placement.width - pallet.width
    underhang = max(0.0, pallet.plan_area - sum(placement.length * placement.width for placement in placements))

    if pallet.height is not None:
        max_z = max((placement.z + placement.height for placement in placements), default=0.0)
        if max_z > pallet.height:
            violations.append(f"Case stacking exceeds pallet height {pallet.height:.3f} with max z {max_z:.3f}.")

    feasible = not violations and len(placements) == len(cases)
    result = LayoutResult(
        placements=placements,
        total_weight=sum(case.weight for case in cases),
        utilization=utilization,
        overhang=overhang,
        underhang=underhang,
        feasible=feasible,
        violations=violations,
    )
    return _score_layout_result(pallet, result), result


def optimize_layout(
    pallet: Pallet,
    cases: Iterable[Case | dict[str, float | str | int]],
    *,
    generations: int = 12,
    population_size: int = 12,
    seed: int = 0,
) -> LayoutResult:
    """GA-style improvement stage on top of the baseline greedy packer.

    The optimizer keeps the original greedy order as a baseline candidate and explores a small
    population of alternative case orders and placement priorities to select the best feasible
    layout by utilization and penalty score.
    """

    rng = random.Random(seed)
    normalized_cases = [_coerce_case(item, pallet.unit) for item in cases]

    expanded_cases = _expand_case_quantities(normalized_cases)
    if not expanded_cases:
        return LayoutResult([], 0.0, 0.0, 0.0, 0.0, False, ["No cases available to place."])

    if not _single_case_type(expanded_cases):
        total_weight = sum(case.weight for case in expanded_cases)
        return LayoutResult(
            placements=[],
            total_weight=total_weight,
            utilization=0.0,
            overhang=0.0,
            underhang=0.0,
            feasible=False,
            violations=["This solver supports a single case type per pallet for now."],
        )

    baseline_order = expanded_cases[:]
    _, baseline_result = _evaluate_case_order(pallet, baseline_order)
    if baseline_result.feasible:
        return baseline_result

    population: list[list[Case]] = [
        baseline_order[:],
        sorted(expanded_cases, key=lambda case: (case.length * case.width, max(case.length, case.width), case.height)),
        sorted(expanded_cases, key=lambda case: (max(case.length, case.width), case.length * case.width, case.height), reverse=True),
        sorted(expanded_cases, key=lambda case: (case.weight, case.length * case.width), reverse=True),
    ]

    for _ in range(max(1, population_size - len(population))):
        shuffled = expanded_cases[:]
        rng.shuffle(shuffled)
        population.append(shuffled)

    best_result: LayoutResult | None = baseline_result
    best_score = _score_layout_result(pallet, baseline_result)
    for _ in range(generations):
        scored = []
        for candidate in population:
            score, result = _evaluate_case_order(pallet, candidate)
            scored.append((score, candidate, result))
        scored.sort(key=lambda item: (1 if item[2].feasible else 0, item[0]), reverse=True)
        elite_count = max(1, min(len(scored), population_size // 2))
        next_population: list[list[Case]] = [candidate for _, candidate, _ in scored[:elite_count]]

        while len(next_population) < population_size:
            parent = scored[rng.randrange(len(scored))][1]
            mutated = parent[:]
            for _ in range(max(1, len(mutated) // 8)):
                idx_a, idx_b = rng.sample(range(len(mutated)), 2)
                mutated[idx_a], mutated[idx_b] = mutated[idx_b], mutated[idx_a]
            next_population.append(mutated)
        population = next_population

        for candidate in population:
            score, result = _evaluate_case_order(pallet, candidate)
            if result.feasible and score > best_score:
                best_score = score
                best_result = result

    if best_result is not None and best_result.feasible:
        return best_result

    return solve_pallet_layout(pallet, expanded_cases, allow_overhang=False)


def solve_pallet_layout(
    pallet: Pallet,
    cases: Iterable[Case | dict[str, float | str | int]],
    *,
    allow_overhang: bool = False,
    optimize: bool = False,
    optimization_generations: int = 12,
    optimization_population: int = 12,
    optimization_seed: int = 0,
) -> LayoutResult:
    """Heuristic layered pallet-loading optimizer used as a practical baseline.

    It supports both US and metric unit conventions and keeps the same public API while
    allowing a range of standard pallet definitions such as CHEP and EUR pallets.
    """

    if not isinstance(pallet, Pallet):
        pallet = Pallet(
            length=float(pallet["length"]),
            width=float(pallet["width"]),
            height=float(pallet["height"]) if pallet.get("height") is not None else None,
            unit=str(pallet.get("unit", "in")),
            max_weight=float(pallet.get("max_weight", 0.0)) if pallet.get("max_weight") is not None else None,
            max_volume=float(pallet.get("max_volume")) if pallet.get("max_volume") is not None else None,
            max_plan_area=float(pallet.get("max_plan_area")) if pallet.get("max_plan_area") is not None else None,
            name=str(pallet.get("name")) if pallet.get("name") is not None else None,
            deck_height=float(pallet["deck_height"]) if pallet.get("deck_height") is not None else None,
        )

    normalized_cases = [_coerce_case(item, pallet.unit) for item in cases]

    expanded_cases = _expand_case_quantities(normalized_cases)
    total_weight = sum(case.weight for case in expanded_cases)
    total_volume = sum(case.volume for case in expanded_cases)

    violations: list[str] = []
    if not _single_case_type(expanded_cases):
        violations.append("This solver supports a single case type per pallet for now.")
        return LayoutResult(
            placements=[],
            total_weight=total_weight,
            utilization=0.0,
            overhang=0.0,
            underhang=0.0,
            feasible=False,
            violations=violations,
        )
    if pallet.max_weight is not None and total_weight > pallet.max_weight:
        violations.append(
            f"Total case weight {total_weight:.3f} exceeds pallet max weight {pallet.max_weight:.3f}."
        )
    if pallet.max_volume is not None and total_volume > pallet.max_volume:
        violations.append(
            f"Total case volume {total_volume:.3f} exceeds pallet max volume {pallet.max_volume:.3f}."
        )
    if pallet.max_plan_area is not None and sum(case.length * case.width for case in expanded_cases) > pallet.max_plan_area:
        violations.append(
            f"Combined plan-view footprint exceeds pallet plan area limit {pallet.max_plan_area:.3f}."
        )

    # Load-level violations (weight, volume, area) can't be fixed by reordering, so only
    # run the optimizer when they are clear; otherwise its result would hide them.
    if optimize and not violations:
        improved = optimize_layout(
            pallet,
            expanded_cases,
            generations=optimization_generations,
            population_size=optimization_population,
            seed=optimization_seed,
        )
        if improved.feasible:
            return improved

    placements, utilization, packing_violations = _pack_layer(pallet, expanded_cases)
    violations.extend(packing_violations)

    overhang = 0.0
    for placement in placements:
        if placement.x + placement.length > pallet.length + 1e-9:
            overhang += placement.x + placement.length - pallet.length
        if placement.y + placement.width > pallet.width + 1e-9:
            overhang += placement.y + placement.width - pallet.width
    underhang = max(0.0, pallet.plan_area - sum(placement.length * placement.width for placement in placements))

    if pallet.height is not None:
        max_z = max((placement.z + placement.height for placement in placements), default=0.0)
        if max_z > pallet.height:
            violations.append(f"Case stacking exceeds pallet height {pallet.height:.3f} with max z {max_z:.3f}.")

    feasible = not violations and len(placements) == len(expanded_cases)
    return LayoutResult(
        placements=placements,
        total_weight=total_weight,
        utilization=utilization,
        overhang=overhang,
        underhang=underhang,
        feasible=feasible,
        violations=violations,
    )


build_layout = solve_pallet_layout
generate_layout = solve_pallet_layout


def main() -> None:
    pallet = Pallet.from_standard("CHEP", unit="in")
    cases = [Case(f"A{i}", 2, 2, 2, weight=1, unit="in") for i in range(15)]
    result = solve_pallet_layout(pallet, cases)
    print(
        {
            "feasible": result.feasible,
            "utilization": round(result.utilization, 4),
            "total_weight": round(result.total_weight, 2),
            "placements": [
                {
                    "case": placement.case_name,
                    "x": placement.x,
                    "y": placement.y,
                    "z": placement.z,
                    "length": placement.length,
                    "width": placement.width,
                    "height": placement.height,
                }
                for placement in result.placements
            ],
            "violations": result.violations,
        }
    )
