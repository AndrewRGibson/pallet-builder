from __future__ import annotations

import random
import time
from bisect import bisect_left, bisect_right
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

    ``height`` is the maximum build height measured from the floor, so it includes the pallet's own
    ``deck_height``; the space left for cases is ``height - deck_height``. With ``height=None`` the
    solver builds a single layer.
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
            raise ValueError("Pallet max build height must be positive when provided.")
        if self.deck_height is not None and self.deck_height <= 0:
            raise ValueError("Pallet deck height must be positive when provided.")
        if self.height is not None and self.deck_height is not None and self.height <= self.deck_height:
            raise ValueError("Pallet max build height must be greater than the deck height.")
        normalize_unit(self.unit)

    @classmethod
    def from_standard(cls, name: str, *, unit: str = "in", max_build_height: float | None = None) -> Pallet:
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
            height=max_build_height,
            unit=unit,
            max_weight=max_weight,
            name=name,
            deck_height=deck_height,
        )

    @property
    def plan_area(self) -> float:
        return self.length * self.width

    @property
    def load_height_limit(self) -> float | None:
        """Height available for cases above the deck, or ``None`` when there is no build limit."""
        if self.height is None:
            return None
        return self.height - (self.deck_height or 0.0)


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
class SolverRun:
    """One solver attempt at a layer pattern, kept so callers can show how the result was found."""

    solver: str
    family: str
    cases_per_layer: int
    target: int
    layers: int
    ran: bool = True
    selected: bool = False
    note: str = ""
    # (generation, best objective, mean objective, best interlock) per GA generation; empty for
    # other solvers.
    history: tuple[tuple[int, float, float, float], ...] = ()
    # Best flip for alternate layers and the interlock it gives (None when stacking is "column").
    flip: str = "none"
    interlock: float | None = None
    # Work done: block packer = region states solved / cuts tried; GA = generations run / distinct
    # patterns decoded. Elapsed time is measured when first computed (results are cached).
    iterations: int = 0
    evaluations: int = 0
    elapsed_ms: float = 0.0


@dataclass
class LayoutResult:
    placements: list[Placement]
    total_weight: float
    utilization: float
    overhang: float
    underhang: float
    feasible: bool
    violations: list[str] = field(default_factory=list)
    layers: int = 0
    cases_per_layer: int = 0
    max_layers: int = 0
    volume_utilization: float = 0.0
    solver_runs: list[SolverRun] = field(default_factory=list)
    # Cases that would fit if they were perfectly malleable (space above the deck / case volume).
    volume_bound: int = 0
    # Stacking: the mode used, how alternate layers are flipped, the share of cases resting on two or
    # more cases below, and the smallest supported share of any case's base.
    stacking: str = "column"
    flip: str = "none"
    interlock: float = 0.0
    min_support: float = 1.0
    stacking_note: str = ""

    @property
    def capacity(self) -> int:
        """Cases that fit by geometry alone (layers that fit the build height x cases per layer)."""
        return self.max_layers * self.cases_per_layer


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


Spots = tuple[tuple[float, float, int], ...]
Footprints = tuple[tuple[float, float], ...]

# Above this many (x, y) normal-position states the recursive guillotine search gets slow in pure
# Python, so the block packer falls back to one-cut (two-block) patterns.
_MAX_GUILLOTINE_STATES = 6000
_UNLIMITED_CUTS = -1


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
) -> tuple[Spots, int, int, float, bool]:
    """Best guillotine layout of identical rectangles, as (x, y, footprint index) tuples.

    Each region is either filled with a uniform grid of one footprint or cut in two at a normal
    position and both halves solved recursively. This finds the classic block patterns (e.g. a
    5x8 case on a 40x48 deck: 48, where the greedy packer manages 45). Also returns the number of
    region states solved, cuts tried, the elapsed milliseconds, and whether the search was simplified
    to two-block patterns because the full search space was too large.
    """
    started = time.perf_counter()
    cuts_tried = 0
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
            nonlocal cuts_tried
            sub_cuts = cuts if cuts == _UNLIMITED_CUTS else cuts - 1
            for x in xs:
                if x >= region_l - 1e-9:
                    break
                if x > 0:
                    cuts_tried += 1
                    count = solve(x, region_w, sub_cuts)[0] + solve(region_l - x, region_w, sub_cuts)[0]
                    if count > best[0]:
                        best = (count, ("v", x, sub_cuts))
            for y in ys:
                if y >= region_w - 1e-9:
                    break
                if y > 0:
                    cuts_tried += 1
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
    ordered = tuple(sorted(spots, key=lambda spot: (spot[1], spot[0])))
    return ordered, len(memo), cuts_tried, (time.perf_counter() - started) * 1000, max_cuts != _UNLIMITED_CUTS


# The GA's per-layer target is the malleable bound (deck area / case footprint); every case short of
# it costs this much, so the objective peaks at the bound itself.
_GA_UNPLACED_PENALTY = 1.0
# Interlock (0-1) is added on top with a weight below the 2-point step of one more case, so it only
# ever breaks ties between layers with the same count.
_GA_INTERLOCK_WEIGHT = 0.999
# Above this many cases per layer the bottom-left decoder gets slow in pure Python.
_GA_MAX_TARGET = 150

# (generations, population, seed, stall). With stall > 0 the GA stops once its best objective hasn't
# improved for that many generations, and ``generations`` becomes the upper limit; 0 runs a fixed count.
GASettings = tuple[int, int, int, int]
DEFAULT_GA: GASettings = (40, 24, 0, 0)

# Stacking modes: "column" repeats one pattern; "interlock" flips alternate layers when that adds
# interlock; "no_column" requires interlock and otherwise limits the load to a single layer.
STACKING_MODES = ("column", "interlock", "no_column")
DEFAULT_STACKING = "interlock"
# A case above must have at least this share of its base resting on cases below.
DEFAULT_MIN_SUPPORT = 0.7
# A case below counts as a support (for interlock) when it carries at least this share of the case above.
_BRIDGE_SHARE = 0.10
FLIP_LABELS = {
    "none": "same pattern as the layer below (column)",
    "mirror_length": "mirrored along the length",
    "mirror_width": "mirrored along the width",
    "rotate_180": "rotated 180\u00b0",
}


def _flip_spots(spots: Spots, footprints: Footprints, length: float, width: float, flip: str) -> Spots:
    flipped = []
    for x, y, index in spots:
        fp_l, fp_w = footprints[index]
        if flip in ("mirror_length", "rotate_180"):
            x = length - x - fp_l
        if flip in ("mirror_width", "rotate_180"):
            y = width - y - fp_w
        flipped.append((round(x, 9), round(y, 9), index))
    return tuple(flipped)


def _rest_stats(upper: Spots, lower: Spots, footprints: Footprints) -> tuple[float, float]:
    """(share of upper cases resting on two or more lower cases, smallest supported share of any)."""
    if not upper:
        return 0.0, 1.0
    widest = max(fp[0] for fp in footprints)
    lower = tuple(sorted(lower))
    lower_x = [spot[0] for spot in lower]
    bridging, min_support = 0, 1.0
    for x, y, index in upper:
        fp_l, fp_w = footprints[index]
        area = fp_l * fp_w
        supporters, supported = 0, 0.0
        for low_x, low_y, low_index in lower[bisect_left(lower_x, x - widest - 1e-9):bisect_left(lower_x, x + fp_l)]:
            low_l, low_w = footprints[low_index]
            overlap_x = min(x + fp_l, low_x + low_l) - max(x, low_x)
            overlap_y = min(y + fp_w, low_y + low_w) - max(y, low_y)
            if overlap_x > 1e-9 and overlap_y > 1e-9:
                supported += overlap_x * overlap_y
                supporters += overlap_x * overlap_y >= _BRIDGE_SHARE * area
        bridging += supporters >= 2
        min_support = min(min_support, supported / area)
    return bridging / len(upper), min_support


@lru_cache(maxsize=4096)
def _best_flip(spots: Spots, footprints: Footprints, length: float, width: float, min_support: float) -> tuple[str, float, float]:
    """Best way to flip alternate layers: (flip, interlock, min support). Column if nothing helps."""
    best = ("none", 0.0, 1.0)
    for flip in ("mirror_length", "mirror_width", "rotate_180"):
        flipped = _flip_spots(spots, footprints, length, width, flip)
        up_interlock, up_support = _rest_stats(flipped, spots, footprints)
        down_interlock, down_support = _rest_stats(spots, flipped, footprints)
        interlock, support = (up_interlock + down_interlock) / 2, min(up_support, down_support)
        if support >= min_support - 1e-9 and interlock > best[1] + 1e-9:
            best = (flip, interlock, support)
    return best


@lru_cache(maxsize=64)
def _ga_layer(
    length: float,
    width: float,
    footprints: Footprints,
    generations: int,
    population: int,
    seed: int,
    stall: int = 0,
    stacking: str = "column",
    min_support: float = DEFAULT_MIN_SUPPORT,
) -> tuple[Spots, tuple[tuple[int, float, float, float], ...], int, float, str]:
    """Genetic search for a single-layer pattern of identical rectangles.

    A chromosome holds one gene per case up to the malleable target; each gene picks the case's
    preferred footprint orientation. Decoding places cases in order at the bottom-left-most free
    position (falling back to the other orientation), which can produce interlocking, non-guillotine
    patterns. Objective = placed - penalty x unplaced, plus (unless stacking is "column") the
    interlock of the pattern's best flip; with "no_column" a pattern that can't interlock is ranked
    below every one that can. Returns the best spots and the per-generation
    (generation, best objective, mean objective, best interlock) history, the number of distinct
    patterns decoded, the elapsed milliseconds, and why it stopped: it reached the bound (with full
    interlock when interlocking), its best objective stalled for ``stall`` generations (when
    ``stall`` > 0), or it hit the ``generations`` limit.
    """
    started = time.perf_counter()
    target = int((length * width + 1e-9) // (footprints[0][0] * footprints[0][1]))
    rng = random.Random(seed)
    choices = len(footprints)
    cache: dict[tuple[int, ...], tuple[float, Spots, float]] = {}

    def decode(genes: tuple[int, ...]) -> Spots:
        free = [(0.0, 0.0, length, width)]
        spots: list[tuple[float, float, int]] = []
        for gene in genes:
            best = None
            for index in (gene, *(i for i in range(choices) if i != gene)):
                fp_l, fp_w = footprints[index]
                for rect_x, rect_y, rect_w, rect_h in free:
                    if fp_l <= rect_w + 1e-9 and fp_w <= rect_h + 1e-9 and (best is None or (rect_y, rect_x) < best[0]):
                        best = ((rect_y, rect_x), rect_x, rect_y, index)
                if best is not None:
                    break
            if best is None:
                break  # identical cases: if this one fits nowhere, none of the rest will
            _, x, y, index = best
            spots.append((round(x, 9), round(y, 9), index))
            free = _split_free_rectangles(free, x, y, *footprints[index])
        return tuple(sorted(spots, key=lambda spot: (spot[1], spot[0])))

    def evaluate(genes: tuple[int, ...]) -> tuple[float, Spots, float]:
        if genes not in cache:
            spots = decode(genes)
            objective = len(spots) - _GA_UNPLACED_PENALTY * (target - len(spots))
            interlock = 0.0
            if stacking != "column":
                interlock = _best_flip(spots, footprints, length, width, min_support)[1]
                objective += _GA_INTERLOCK_WEIGHT * interlock
                if stacking == "no_column" and interlock <= 0:
                    objective -= 2 * target + 1
            cache[genes] = (objective, spots, interlock)
        return cache[genes]

    def tournament(scored: list[tuple[float, tuple[int, ...]]]) -> tuple[int, ...]:
        return max(rng.sample(scored, min(3, len(scored))))[1]

    pop = [tuple([0] * target), tuple([1 % choices] * target), tuple(i % choices for i in range(target))]
    while len(pop) < population:
        pop.append(tuple(rng.randrange(choices) for _ in range(target)))

    history: list[tuple[int, float, float, float]] = []
    improved_at, best_so_far = 0, float("-inf")
    stop_reason = f"generation limit ({generations})"
    for generation in range(generations + 1):
        scored = sorted(((evaluate(genes)[0], genes) for genes in pop), reverse=True)
        best_objective, best_genes = scored[0]
        _, best_spots, best_interlock = evaluate(best_genes)
        history.append((generation, best_objective, sum(score for score, _ in scored) / len(scored), best_interlock))
        if best_objective > best_so_far + 1e-9:
            improved_at, best_so_far = generation, best_objective
        if len(best_spots) >= target and (stacking == "column" or best_interlock >= 1 - 1e-9):
            stop_reason = "reached the bound"
            break
        if stall and generation - improved_at >= stall:
            stop_reason = f"no improvement for {stall} generations"
            break
        if generation == generations:
            break
        children = [genes for _, genes in scored[:2]]  # elitism
        while len(children) < population:
            first, second = tournament(scored), tournament(scored)
            cut_a, cut_b = sorted(rng.sample(range(target + 1), 2))  # two-point crossover
            child = list(first[:cut_a] + second[cut_a:cut_b] + first[cut_b:])
            for i in range(target):
                if rng.random() < 1.5 / target:
                    child[i] = rng.randrange(choices)
            if rng.random() < 0.3:  # block mutation: re-orient a run of consecutive cases
                start, end = sorted(rng.sample(range(target + 1), 2))
                value = rng.randrange(choices)
                child[start:end] = [value] * (end - start)
            children.append(tuple(child))
        pop = children

    elapsed_ms = (time.perf_counter() - started) * 1000
    return evaluate(best_genes)[1], tuple(history), len(cache), elapsed_ms, stop_reason


@dataclass(frozen=True)
class _Options:
    ga: GASettings | None = DEFAULT_GA
    stacking: str = DEFAULT_STACKING
    min_support: float = DEFAULT_MIN_SUPPORT


_DEFAULT_OPTIONS = _Options()


@dataclass(frozen=True)
class _LayerPlan:
    spots: Spots
    footprints: Footprints
    orientations: tuple[tuple[int, int, int], ...]
    layer_height: float
    layers: int
    flip: str = "none"
    interlock: float = 0.0
    min_support: float = 1.0
    note: str = ""

    @property
    def capacity(self) -> int:
        return self.layers * len(self.spots)


def _stack_plan(
    spots: Spots,
    run: SolverRun,
    footprints: Footprints,
    orientations: tuple[tuple[int, int, int], ...],
    layer_height: float,
    layers: int,
    deck: tuple[float, float],
    interlocking: bool,
    opts: _Options,
) -> tuple[tuple, _LayerPlan]:
    """Build a layer plan from a pattern: choose the alternate-layer flip and apply the stacking rule.

    Returns the ranking key (capacity, cases per layer, interlock) and the plan; also records the
    flip and interlock on ``run``.
    """
    flip, interlock, support = "none", 0.0, 1.0
    if interlocking and spots:
        flip, interlock, support = _best_flip(spots, footprints, *deck, opts.min_support)
    run.flip, run.interlock = flip, (interlock if interlocking else None)
    usable_layers, note = layers, ""
    if opts.stacking == "no_column" and interlock <= 0 and layers > 1:
        usable_layers = 1
        note = ("Column stacking is disallowed and no interlocking pattern keeps every case "
                f"{opts.min_support:.0%} supported, so the load is limited to one layer.")
    plan = _LayerPlan(spots, footprints, orientations, layer_height, usable_layers, flip, interlock, support, note)
    return (plan.capacity, len(spots), interlock), plan


def _plan_layers(pallet: Pallet, case: Case, opts: _Options = _DEFAULT_OPTIONS) -> tuple[_LayerPlan | None, list[SolverRun]]:
    """Pick the orientation family and layer pattern that stack the most cases within the build height.

    Orientations are grouped by which case dimension stands vertical, so every layer has one height
    and a flat top. Each family gets a layer pattern from the block packer and, where it can help,
    from the GA. Unless stacking is "column", alternate layers use the pattern's best flip (mirror or
    180 degree turn) when that makes cases bridge the seams below while keeping each case at least
    ``min_support`` supported. With "no_column", a pattern that can't interlock is limited to one
    layer. Candidates rank by capacity, then cases per layer, then interlock. If no orientation fits
    the height, the best layer is returned with ``layers=0`` so the caller can report the height
    violation. Also returns a log of every solver run.
    """
    limit = pallet.load_height_limit
    groups: dict[float, list[tuple[int, int, int]]] = {}
    for orientation in _orientations_for(case):
        groups.setdefault(round(case.oriented_dimensions(orientation)[2], 9), []).append(orientation)

    best: tuple[tuple, _LayerPlan, SolverRun] | None = None
    runs: list[SolverRun] = []
    length, width = round(pallet.length, 9), round(pallet.width, 9)
    for layer_height, orientations in groups.items():
        footprint_list: list[tuple[float, float]] = []
        footprint_orientations: list[tuple[int, int, int]] = []
        for orientation in orientations:
            fp_l, fp_w, _ = case.oriented_dimensions(orientation)
            footprint = (round(fp_l, 9), round(fp_w, 9))
            if footprint not in footprint_list:
                footprint_list.append(footprint)
                footprint_orientations.append(orientation)
        footprints = tuple(footprint_list)
        layers = 1 if limit is None else int((limit + 1e-9) // layer_height)
        target = int((length * width + 1e-9) // (footprints[0][0] * footprints[0][1]))
        family = f"{layer_height:g} {pallet.unit} tall layers"

        # Interlock only matters when layers actually stack on each other.
        interlocking = opts.stacking != "column" and layers >= 2
        stack_args = (footprints, tuple(footprint_orientations), layer_height, layers, (length, width),
                      interlocking, opts)

        block_spots, states, cuts_tried, block_ms, simplified = _block_layout(length, width, footprints)
        block_note = "Recursive guillotine search over block patterns."
        if simplified:
            block_note += (" The full search was too large, so it was limited to two-block patterns; "
                           "denser layouts may exist.")
        block_run = SolverRun("Block packer", family, len(block_spots), target, layers, note=block_note,
                              iterations=states, evaluations=cuts_tried, elapsed_ms=block_ms)
        candidates = [(*_stack_plan(block_spots, block_run, *stack_args), block_run)]
        runs.append(block_run)

        if opts.ga is not None:
            reaches_bound = len(block_spots) >= target
            fully_interlocked = not interlocking or (block_run.interlock or 0.0) >= 1 - 1e-9
            skip = None
            if reaches_bound and fully_interlocked:
                skip = ("Skipped: the block packer already reaches the bound"
                        + (" with full interlock." if interlocking else "."))
            elif len(footprints) < 2:
                skip = "Skipped: a square footprint has only one orientation."
            elif target > _GA_MAX_TARGET:
                skip = f"Skipped: target of {target} cases per layer exceeds the GA limit of {_GA_MAX_TARGET}."
            if skip:
                runs.append(SolverRun("Genetic algorithm", family, 0, target, layers, ran=False, note=skip))
            else:
                # Optimize count (+ interlock when stacking interlocks). With interlock required, a
                # second pass that penalizes non-interlocking patterns runs only if the first found none.
                passes = ["interlock" if interlocking else "column"]
                for stacking in passes:
                    ga_spots, history, decoded, ga_ms, stopped = _ga_layer(
                        length, width, footprints, *opts.ga, stacking, opts.min_support)
                    goal = {"column": "count", "interlock": "count, then interlock",
                            "no_column": "count with interlock required"}[stacking]
                    note = (f"Population {opts.ga[1]}, seed {opts.ga[2]}; objective: {goal}; "
                            f"stopped after {len(history) - 1} generations: {stopped}.")
                    name = "Genetic algorithm" if stacking != "no_column" else "Genetic algorithm (interlock required)"
                    ga_run = SolverRun(name, family, len(ga_spots), target, layers, note=note, history=history,
                                       iterations=len(history) - 1, evaluations=decoded, elapsed_ms=ga_ms)
                    candidates.append((*_stack_plan(ga_spots, ga_run, *stack_args), ga_run))
                    runs.append(ga_run)
                    if opts.stacking == "no_column" and interlocking and stacking == "interlock" and not ga_run.interlock:
                        passes.append("no_column")

        # The GA must strictly beat the block packer on (capacity, cases per layer, interlock).
        key, plan, run = candidates[0]
        for cand_key, cand_plan, cand_run in candidates[1:]:
            if cand_key > key:
                key, plan, run = cand_key, cand_plan, cand_run
        if not plan.spots:
            continue
        if best is None or key > best[0]:
            best = (key, plan, run)

    if best is None:
        return None, runs
    best[2].selected = True
    return best[1], runs


def _pack_layer(
    pallet: Pallet, cases: Sequence[Case], opts: _Options = _DEFAULT_OPTIONS
) -> tuple[list[Placement], list[str], _LayerPlan | None, list[SolverRun]]:
    """Stack identical cases in flat layers; returns placements, violations, the plan and solver log."""
    plan, runs = _plan_layers(pallet, cases[0], opts)
    if plan is None:
        return [], ["No cases could be placed on the pallet."], None, runs

    per_layer = len(plan.spots)
    alternate = _flip_spots(plan.spots, plan.footprints, round(pallet.length, 9), round(pallet.width, 9), plan.flip)
    # Stack whole layers, flipping every other one; a partial top layer fills in pattern order. With
    # no layer fitting the height, still place one layer so the height check explains the failure.
    available_layers = max(plan.layers, 1)
    placements: list[Placement] = []
    for index, item in enumerate(cases[: per_layer * available_layers]):
        layer, slot = divmod(index, per_layer)
        x, y, footprint_index = (alternate if layer % 2 else plan.spots)[slot]
        orientation = plan.orientations[footprint_index]
        fp_l, fp_w, height = item.oriented_dimensions(orientation)
        placements.append(Placement(item.name, x, y, layer * plan.layer_height, fp_l, fp_w, height, orientation))

    violations = [f"No feasible footprint for case {item.name!r} on the pallet." for item in cases[len(placements):]]
    return placements, violations, plan, runs


def maximize_case_count(
    pallet: Pallet,
    case: Case | dict[str, float | str | int],
    *,
    progress_callback: callable | None = None,
    optimize: bool = True,
    optimization_generations: int = DEFAULT_GA[0],
    optimization_population: int = DEFAULT_GA[1],
    optimization_seed: int = DEFAULT_GA[2],
    optimization_stall: int = DEFAULT_GA[3],
    stacking: str = DEFAULT_STACKING,
    min_support: float = DEFAULT_MIN_SUPPORT,
) -> tuple[int, LayoutResult]:
    """Return the maximum number of identical cases that fit on a pallet.

    Capacity is the number of layers that fit the build height times the cases per layer, capped
    by the weight, volume and plan-area limits. Returns the count and the layout that achieves it.
    ``progress_callback`` is kept for compatibility and is called once with the final result.
    With ``optimize`` the GA searches for a denser layer wherever the block packer falls short of the
    malleable bound; ``LayoutResult.solver_runs`` records what each solver found. ``stacking`` and
    ``min_support`` control interlocking (see ``solve_pallet_layout``).
    """

    case = _coerce_case(case, pallet.unit)

    if not _fits_footprint(case, pallet):
        return 0, LayoutResult([], 0.0, 0.0, 0.0, 0.0, False, ["Case footprint exceeds pallet footprint in every allowed orientation."])

    if case.quantity <= 0:
        raise ValueError("Case quantity must be positive for max-case search.")

    solve_options = {
        "optimize": optimize,
        "optimization_generations": optimization_generations,
        "optimization_population": optimization_population,
        "optimization_seed": optimization_seed,
        "optimization_stall": optimization_stall,
        "stacking": stacking,
        "min_support": min_support,
    }
    plan, _ = _plan_layers(pallet, case, _options(**solve_options))
    count = plan.capacity if plan is not None else 0
    if pallet.max_weight is not None and case.weight > 0:
        count = min(count, int(pallet.max_weight // case.weight))
    if pallet.max_plan_area is not None:
        count = min(count, int(pallet.max_plan_area // case.footprint_area))
    if pallet.max_volume is not None:
        count = min(count, int(pallet.max_volume // case.volume))

    if count <= 0:
        # Solve a single case so the caller sees which limit (height, weight, ...) rules it out.
        return _explain_single_case(pallet, case, solve_options)

    result = solve_pallet_layout(pallet, [replace(case, quantity=count)], **solve_options)
    if progress_callback is not None:
        progress_callback(1, count, count, count, result)
    if not result.feasible:
        return _explain_single_case(pallet, case, solve_options)
    return count, result


def _options(
    optimize: bool,
    optimization_generations: int,
    optimization_population: int,
    optimization_seed: int,
    optimization_stall: int,
    stacking: str,
    min_support: float,
) -> _Options:
    if stacking not in STACKING_MODES:
        raise ValueError(f"Unknown stacking mode {stacking!r}. Use one of: {', '.join(STACKING_MODES)}.")
    if not 0.0 <= min_support <= 1.0:
        raise ValueError("min_support must be between 0 and 1.")
    if optimization_stall < 0:
        raise ValueError("optimization_stall must be 0 (fixed generations) or a positive number of generations.")
    ga = (optimization_generations, optimization_population, optimization_seed, optimization_stall) if optimize else None
    return _Options(ga, stacking, min_support)


def _explain_single_case(pallet: Pallet, case: Case, solve_options: dict | None = None) -> tuple[int, LayoutResult]:
    result = solve_pallet_layout(pallet, [replace(case, quantity=1)], **(solve_options or {}))
    violations = result.violations or ["No cases fit on this pallet."]
    return 0, LayoutResult([], 0.0, 0.0, 0.0, 0.0, False, violations, solver_runs=result.solver_runs,
                           volume_bound=result.volume_bound, stacking=result.stacking)


def _single_case_type(cases: Sequence[Case]) -> bool:
    if not cases:
        return True
    signature = (cases[0].length, cases[0].width, cases[0].height)
    return all((case.length, case.width, case.height) == signature for case in cases[1:])


def _evaluate_load(
    pallet: Pallet,
    cases: Sequence[Case],
    violations: list[str] | None = None,
    opts: _Options = _DEFAULT_OPTIONS,
) -> LayoutResult:
    placements, packing_violations, plan, runs = _pack_layer(pallet, cases, opts)
    violations = [*(violations or []), *packing_violations]

    overhang = 0.0
    for placement in placements:
        if placement.x + placement.length > pallet.length + 1e-9:
            overhang += placement.x + placement.length - pallet.length
        if placement.y + placement.width > pallet.width + 1e-9:
            overhang += placement.y + placement.width - pallet.width
    base = [placement for placement in placements if placement.z <= 1e-9]
    base_area = sum(placement.length * placement.width for placement in base)
    underhang = max(0.0, pallet.plan_area - base_area)

    case = cases[0]
    limit = pallet.load_height_limit
    volume_utilization = 0.0
    if limit is not None:
        load_height = max((placement.z + placement.height for placement in placements), default=0.0)
        if load_height > limit + 1e-9:
            violations.append(
                f"Load height {load_height:.3f} exceeds the {limit:.3f} available above the deck "
                f"(max build height {pallet.height:.3f})."
            )
        placed_volume = sum(placement.length * placement.width * placement.height for placement in placements)
        volume_utilization = placed_volume / (pallet.plan_area * limit)
        volume_bound = int((pallet.plan_area * limit + 1e-9) // case.volume)
    else:
        # No build limit means a single layer: the bound is deck area over the smallest footprint.
        smallest = min(case.oriented_dimensions(o)[0] * case.oriented_dimensions(o)[1] for o in _orientations_for(case))
        volume_bound = int((pallet.plan_area + 1e-9) // smallest)

    return LayoutResult(
        placements=placements,
        total_weight=sum(item.weight for item in cases),
        utilization=base_area / pallet.plan_area,
        overhang=overhang,
        underhang=underhang,
        feasible=not violations and len(placements) == len(cases),
        violations=violations,
        layers=len({placement.z for placement in placements}),
        cases_per_layer=len(plan.spots) if plan else 0,
        max_layers=plan.layers if plan else 0,
        volume_utilization=volume_utilization,
        solver_runs=runs,
        volume_bound=volume_bound,
        stacking=opts.stacking,
        flip=plan.flip if plan else "none",
        interlock=plan.interlock if plan else 0.0,
        min_support=plan.min_support if plan else 1.0,
        stacking_note=plan.note if plan else "",
    )


def optimize_layout(
    pallet: Pallet,
    cases: Iterable[Case | dict[str, float | str | int]],
    *,
    generations: int = DEFAULT_GA[0],
    population_size: int = DEFAULT_GA[1],
    seed: int = DEFAULT_GA[2],
    stall: int = DEFAULT_GA[3],
) -> LayoutResult:
    """Solve with the GA layer search enabled (kept for API compatibility)."""
    return solve_pallet_layout(
        pallet,
        cases,
        optimize=True,
        optimization_generations=generations,
        optimization_population=population_size,
        optimization_seed=seed,
        optimization_stall=stall,
    )


def solve_pallet_layout(
    pallet: Pallet,
    cases: Iterable[Case | dict[str, float | str | int]],
    *,
    allow_overhang: bool = False,
    optimize: bool = True,
    optimization_generations: int = DEFAULT_GA[0],
    optimization_population: int = DEFAULT_GA[1],
    optimization_seed: int = DEFAULT_GA[2],
    optimization_stall: int = DEFAULT_GA[3],
    stacking: str = DEFAULT_STACKING,
    min_support: float = DEFAULT_MIN_SUPPORT,
) -> LayoutResult:
    """Stack the given identical cases in flat layers on the pallet.

    Each layer pattern comes from the block packer and, with ``optimize``, the GA layer search
    (used wherever it can add cases or, when interlocking, stability). ``stacking`` is "column"
    (same pattern every layer), "interlock" (flip alternate layers when that bridges seams; the
    default) or "no_column" (interlock required, otherwise one layer). ``optimization_stall`` > 0
    stops the GA once its best objective hasn't improved for that many generations, with
    ``optimization_generations`` as the upper limit (0 runs a fixed count). ``min_support`` is the
    smallest share of a case's base that must rest on cases below. Supports US and metric units and
    the standard CHEP/GMA/EUR pallet definitions.
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

    if not expanded_cases:
        return LayoutResult([], 0.0, 0.0, 0.0, 0.0, False, ["No cases available to place."])
    opts = _options(optimize, optimization_generations, optimization_population, optimization_seed,
                    optimization_stall, stacking, min_support)
    return _evaluate_load(pallet, expanded_cases, violations, opts)


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
