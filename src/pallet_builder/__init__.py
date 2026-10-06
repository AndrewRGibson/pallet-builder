from ._version import get_version
from .solver import (
    DEFAULT_MIN_SUPPORT,
    DEFAULT_STACKING,
    FLIP_LABELS,
    STACKING_MODES,
    STANDARD_PALLETS,
    Case,
    LayoutResult,
    Pallet,
    Placement,
    SolverRun,
    build_layout,
    convert_length,
    generate_layout,
    main,
    maximize_case_count,
    normalize_unit,
    optimize_layout,
    solve_pallet_layout,
)

__all__ = [
    "DEFAULT_MIN_SUPPORT",
    "DEFAULT_STACKING",
    "FLIP_LABELS",
    "STACKING_MODES",
    "STANDARD_PALLETS",
    "Case",
    "LayoutResult",
    "Pallet",
    "Placement",
    "SolverRun",
    "build_layout",
    "convert_length",
    "generate_layout",
    "main",
    "maximize_case_count",
    "normalize_unit",
    "optimize_layout",
    "solve_pallet_layout",
]

__version__ = get_version()
