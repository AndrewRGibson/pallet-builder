"""Plain-language opportunities and risks from a case-size sensitivity analysis.

Everything here is computed from the solved variants, so every number in the text can be checked
against the sensitivity table. (It also makes a reliable fact base if a language model is later
asked to write a narrative summary.)
"""

from __future__ import annotations

from dataclasses import dataclass

DIMENSIONS = ("length", "width", "height")


@dataclass(frozen=True)
class Variant:
    """One solved case size: its dimensions and the resulting load."""

    length: float
    width: float
    height: float
    cases: int
    ti: int  # cases per layer
    hi: int  # layers

    def dims(self) -> tuple[float, float, float]:
        return self.length, self.width, self.height


@dataclass(frozen=True)
class Insight:
    kind: str  # "gain", "risk" or "info"
    text: str
    variant: Variant | None = None


def _deltas(base: Variant, variant: Variant) -> dict[str, float]:
    return {name: round(new - old, 6) for name, old, new in zip(DIMENSIONS, base.dims(), variant.dims())}


def _relative_change(base: Variant, variant: Variant) -> float:
    """Total size change, as the sum of each dimension's relative change (for "smallest change")."""
    return sum(abs(delta) / old for delta, old in zip(_deltas(base, variant).values(), base.dims()) if old)


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _describe_change(base: Variant, variant: Variant, unit: str) -> str:
    """e.g. "reduce the length by 0.25 in (9 → 8.75) and the height by 0.5 in (8 → 7.5)"."""
    groups: dict[str, list[str]] = {"reduce": [], "increase": []}
    for (name, delta), old, new in zip(_deltas(base, variant).items(), base.dims(), variant.dims()):
        if delta:
            groups["reduce" if delta < 0 else "increase"].append(
                f"the {name} by {abs(delta):g} {unit} ({old:g} → {new:g})")
    return " and ".join(f"{verb} {_join(parts)}" for verb, parts in groups.items() if parts)


def _why(base: Variant, variant: Variant) -> str:
    """What changed in the stack: cases per layer (Ti) and/or layers (Hi)."""
    reasons = []
    if variant.ti != base.ti:
        more = variant.ti > base.ti
        count = abs(variant.ti - base.ti)
        reasons.append(f"{count} {'more' if more else 'fewer'} {'case' if count == 1 else 'cases'} per layer "
                       f"(Ti {base.ti} → {variant.ti})")
    if variant.hi != base.hi:
        more = variant.hi > base.hi
        count = abs(variant.hi - base.hi)
        reasons.append(f"{count} {'more' if more else 'fewer'} {'layer' if count == 1 else 'layers'} "
                       f"(Hi {base.hi} → {variant.hi})")
    return " and ".join(reasons) or "the same Ti × Hi, with a different limit binding"


def _weight_cap(variant: Variant, max_weight: float | None, case_weight: float) -> int | None:
    """The weight-limited case count, if max weight (not space) is what caps this variant."""
    if max_weight is None or case_weight <= 0:
        return None
    cap = int(max_weight // case_weight)
    return cap if variant.cases == cap < variant.ti * variant.hi else None


def sensitivity_insights(
    base: Variant,
    variants: list[Variant],
    unit: str,
    *,
    max_weight: float | None = None,
    case_weight: float = 0.0,
    max_gains: int = 4,
) -> list[Insight]:
    """Opportunities (size changes that add cases) and risks (small changes that lose cases).

    Gains are the Pareto-best variants: no other variant adds at least as many cases with a smaller
    total size change. They read as a ladder from the smallest change that gains anything up to the
    largest gain (at most ``max_gains``, always keeping the largest). Risks give, for each dimension
    and direction, the smallest single-dimension change that loses cases.
    """
    insights: list[Insight] = []
    gainers = [v for v in variants if v.cases > base.cases]
    pareto = [
        v for v in gainers
        if not any(
            other is not v
            and other.cases >= v.cases
            and _relative_change(base, other) <= _relative_change(base, v)
            and (other.cases > v.cases or _relative_change(base, other) < _relative_change(base, v))
            for other in gainers
        )
    ]
    pareto.sort(key=lambda v: (_relative_change(base, v), -v.cases))
    ladder = pareto if len(pareto) <= max_gains else [*pareto[: max_gains - 1], pareto[-1]]
    for variant in ladder:
        gain = variant.cases - base.cases
        text = (f"If you can {_describe_change(base, variant, unit)}, the pallet holds {variant.cases} cases "
                f"instead of {base.cases}: +{gain} cases (+{gain / base.cases:.0%} case density), from "
                f"{_why(base, variant)}.")
        cap = _weight_cap(variant, max_weight, case_weight)
        if cap is not None:
            text += (f" Max weight caps it at {cap}; the space would take {variant.ti * variant.hi}, so a lighter "
                     "case or higher weight rating gains more.")
        insights.append(Insight("gain", text, variant))

    for index, name in enumerate(DIMENSIONS):
        for direction in (1, -1):
            single = [
                v for v in variants
                if v.cases < base.cases
                and all((delta * direction > 0) if i == index else delta == 0
                        for i, delta in enumerate(_deltas(base, v).values()))
            ]
            if not single:
                continue
            smallest = min(single, key=lambda v: abs(_deltas(base, v)[name]))
            loss = base.cases - smallest.cases
            change = _describe_change(base, smallest, unit)
            insights.append(Insight(
                "risk",
                f"Watch the {name} tolerance: if you {change}, the pallet loses {loss} cases "
                f"(−{loss / base.cases:.0%}), from {_why(base, smallest)}.",
                smallest,
            ))

    if not gainers:
        insights.insert(0, Insight("info", "No size change in the tested range adds cases: the current case size is "
                                           "already the best of the variants tried."))
    return insights
