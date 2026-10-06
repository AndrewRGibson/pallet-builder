from pallet_builder import (
    STANDARD_PALLETS,
    Case,
    Pallet,
    convert_length,
    maximize_case_count,
    optimize_layout,
    solve_pallet_layout,
)


def test_layout_fits_basic_pallet():
    pallet = Pallet(length=10, width=8, height=5, max_weight=2000)
    cases = [
        Case("A", 4, 2, 2, weight=100),
        Case("B", 4, 2, 2, weight=100),
        Case("C", 4, 2, 2, weight=100),
    ]

    result = solve_pallet_layout(pallet, cases)

    assert result.feasible
    assert result.total_weight <= pallet.max_weight
    assert result.utilization > 0.0
    assert len(result.placements) == len(cases)


def test_layout_rejects_overweight_or_space_issue():
    pallet = Pallet(length=10, width=8, height=5, max_weight=120)
    cases = [
        Case("A", 5, 4, 3, weight=60),
        Case("B", 5, 4, 3, weight=70),
    ]

    result = solve_pallet_layout(pallet, cases)

    assert not result.feasible
    assert result.violations


def test_standard_profile_includes_chep_and_metric_equivalents():
    chep = Pallet.from_standard("CHEP", unit="in")
    assert chep.length == 40
    assert chep.width == 48
    assert chep.deck_height == 6
    assert chep.height is None
    assert chep.max_weight == 2200

    eur = Pallet.from_standard("EUR_1200x800", unit="mm")
    assert eur.length == 1200
    assert eur.width == 800
    assert eur.unit == "mm"


def test_metric_and_us_units_are_consistent():
    assert convert_length(40, "in", "mm") == 1016.0
    assert convert_length(1000, "mm", "in") == 39.37007874015748

    pallet = Pallet(length=40, width=48, height=6, unit="in", max_weight=2200)
    cases = [
        Case("A", 4, 4, 4, weight=10, unit="in"),
        Case("B", 4, 4, 4, weight=10, unit="in"),
        Case("C", 4, 4, 4, weight=10, unit="in"),
    ]

    result = solve_pallet_layout(pallet, cases)
    assert result.feasible
    assert len(result.placements) == 3


def test_large_layer_counts_fit_small_cases_on_standard_pallets():
    for count in [2, 5, 12, 25, 75, 150]:
        for pallet_name, unit, case_size in [
            ("CHEP", "in", 2),
            ("EUR_1200x800", "mm", 50),
        ]:
            pallet = Pallet.from_standard(pallet_name, unit=unit)
            cases = [Case(f"C{i}", case_size, case_size, case_size, weight=1, unit=unit) for i in range(count)]

            result = solve_pallet_layout(pallet, cases)

            assert result.feasible, (pallet_name, count, result.violations)
            assert len(result.placements) == count, (pallet_name, count, len(result.placements))
            assert result.utilization > 0.0


def test_optimization_improves_or_matches_the_greedy_layout():
    pallet = Pallet(length=20, width=10, height=4, unit="in", max_weight=2000)
    cases = [Case(f"C{i}", 4, 4, 2, weight=3, unit="in") for i in range(10)]

    baseline = solve_pallet_layout(pallet, cases)
    improved = optimize_layout(pallet, cases)

    assert baseline.feasible
    assert improved.feasible
    assert improved.utilization >= baseline.utilization


def test_solver_requires_single_case_type_per_pallet_for_now():
    pallet = Pallet(length=10, width=8, height=5, max_weight=1000)
    cases = [Case("A", 4, 2, 2, weight=5), Case("B", 3, 2, 2, weight=5)]

    result = solve_pallet_layout(pallet, cases)
    optimized = optimize_layout(pallet, cases)

    assert not result.feasible
    assert "single case type" in " ".join(result.violations).lower()
    assert not optimized.feasible
    assert "single case type" in " ".join(optimized.violations).lower()


def test_single_case_type_handles_a_broad_case_count_matrix():
    scenarios = [
        (Pallet(length=20, width=10, height=4, unit="in"), 2, [1, 3, 6, 10, 15]),
        (Pallet(length=40, width=48, height=6, unit="in"), 4, [2, 5, 10, 20, 40]),
        (Pallet(length=1200, width=800, height=144, unit="mm"), 50, [2, 5, 10, 20, 35]),
        (Pallet(length=1000, width=1200, height=144, unit="mm"), 60, [2, 5, 10, 15]),
    ]

    for pallet, case_size, counts in scenarios:
        for count in counts:
            cases = [Case(f"C{i}", case_size, case_size, 2, weight=1, unit=pallet.unit) for i in range(count)]
            result = solve_pallet_layout(pallet, cases)
            assert result.feasible, (pallet, case_size, count, result.violations)
            assert len(result.placements) == count, (pallet, case_size, count, len(result.placements))
            assert result.utilization > 0.0


def test_single_case_type_works_across_unit_conversions_and_orientations():
    pallet = Pallet(length=40, width=48, height=6, unit="in", max_weight=2000)
    for case_size in [2, 4, 6, 8]:
        cases = [Case(f"S{i}", case_size, case_size, 2, weight=2, unit="in") for i in range(12)]
        result = solve_pallet_layout(pallet, cases)
        assert result.feasible, (case_size, result.violations)
        assert len(result.placements) == 12

    metric_pallet = Pallet(length=1200, width=800, height=150, unit="mm")
    metric_cases = [Case(f"M{i}", 100, 100, 50, weight=1, unit="mm") for i in range(10)]
    metric_result = solve_pallet_layout(metric_pallet, metric_cases)
    assert metric_result.feasible
    assert len(metric_result.placements) == 10


def test_optimization_matches_baseline_for_repeated_case_types():
    pallet = Pallet(length=20, width=10, height=4, unit="in")
    per_size_cases = [
        [Case(f"C{i}", 2, 2, 2, weight=1, unit="in") for i in range(12)],
        [Case(f"C{i}", 4, 4, 2, weight=2, unit="in") for i in range(10)],
        [Case(f"C{i}", 6, 6, 2, weight=3, unit="in") for i in range(3)],
        [Case(f"C{i}", 8, 8, 2, weight=4, unit="in") for i in range(2)],
    ]

    for cases in per_size_cases:
        baseline = solve_pallet_layout(pallet, cases)
        improved = optimize_layout(pallet, cases)
        assert baseline.feasible, (len(cases), baseline.violations)
        assert improved.feasible, (len(cases), improved.violations)
        assert improved.utilization >= baseline.utilization - 1e-9


def test_maximize_case_count_for_single_type():
    pallet = Pallet(length=10, width=8, height=5, unit="in", max_weight=2000)
    case = Case("A", 4, 2, 2, weight=100, unit="in")

    max_count, result = maximize_case_count(pallet, case)

    assert max_count == 10
    assert result.feasible
    assert len(result.placements) == 10


def test_maximize_case_count_handles_single_positive_fit_without_zero_quantity_search():
    pallet = Pallet(length=10, width=8, height=5, unit="in", max_weight=2000)
    case = Case("A", 9, 5, 2, weight=100, unit="in")

    max_count, result = maximize_case_count(pallet, case)

    assert max_count == 1
    assert result.feasible
    assert len(result.placements) == 1


def test_mixed_case_geometry_rejected_with_clear_reason():
    pallet = Pallet(length=12, width=8, height=5, max_weight=1000)
    mixed_cases = [
        Case("A", 4, 2, 2, weight=5),
        Case("B", 3, 2, 2, weight=5),
        Case("C", 2, 2, 2, weight=5),
    ]

    result = solve_pallet_layout(pallet, mixed_cases)
    optimized = optimize_layout(pallet, mixed_cases)

    assert not result.feasible
    assert not optimized.feasible
    assert "single case type" in " ".join(result.violations).lower()
    assert "single case type" in " ".join(optimized.violations).lower()


def test_preset_deck_height_does_not_limit_case_height():
    chep = Pallet.from_standard("CHEP", unit="in")
    max_count, result = maximize_case_count(chep, Case("T", 12, 10, 8, weight=10))

    assert max_count > 0
    assert result.feasible

    capped = Pallet.from_standard("CHEP", unit="in", max_load_height=6)
    max_count, result = maximize_case_count(capped, Case("T", 12, 10, 8, weight=10))

    assert max_count == 0
    assert "height" in " ".join(result.violations).lower()


def test_this_side_up_cases_are_never_tipped():
    pallet = Pallet(length=10, width=10, height=5, unit="in")
    result = solve_pallet_layout(pallet, [Case("F", 12, 4, 2)])

    assert not result.feasible
    assert all(placement.orientation[2] == 2 for placement in result.placements)


def test_tipped_case_reports_its_oriented_height():
    pallet = Pallet(length=10, width=10, height=20, unit="in")
    result = solve_pallet_layout(pallet, [Case("F", 12, 4, 2, this_side_up=False)])

    assert result.feasible
    (placement,) = result.placements
    assert {placement.length, placement.width, placement.height} == {12, 4, 2}
    assert placement.length <= 10 and placement.width <= 10

    # Every orientation that fits a 10x10 deck stands the 12" side up, so a 5" cap rules it out.
    short_pallet = Pallet(length=10, width=10, height=5, unit="in")
    result = solve_pallet_layout(short_pallet, [Case("F", 12, 4, 2, this_side_up=False)])
    assert not result.feasible
    assert "height" in " ".join(result.violations).lower()


def test_tippable_case_prefers_orientation_within_height_limit():
    pallet = Pallet(length=20, width=20, height=5, unit="in")
    result = solve_pallet_layout(pallet, [Case("L", 4, 4, 10, this_side_up=False)])

    assert result.feasible
    assert result.placements[0].height == 4


def test_maximize_case_count_considers_rotated_footprint():
    pallet = Pallet(length=40, width=48, unit="in")
    max_count, result = maximize_case_count(pallet, Case("R", 45, 10, 5))

    assert max_count == 4
    assert result.feasible
    assert all(placement.length == 10 and placement.width == 45 for placement in result.placements)


def test_optimize_does_not_hide_load_violations():
    pallet = Pallet(length=10, width=10, height=5, max_weight=5)
    result = solve_pallet_layout(pallet, [Case("W", 5, 5, 2, weight=10, quantity=2)], optimize=True)

    assert not result.feasible
    assert "weight" in " ".join(result.violations).lower()


def test_standard_pallet_aliases_resolve_without_duplicate_presets():
    assert Pallet.from_standard("EURO", unit="mm").length == 1200
    assert Pallet.from_standard("eur_1200x800", unit="mm").width == 800
    assert sorted(STANDARD_PALLETS) == ["CHEP", "EUR_1000X1200", "EUR_1200X800", "GMA"]


def _assert_valid_layer(pallet, placements):
    for p in placements:
        assert p.x >= -1e-9 and p.y >= -1e-9
        assert p.x + p.length <= pallet.length + 1e-6 and p.y + p.width <= pallet.width + 1e-6
    for i, a in enumerate(placements):
        for b in placements[i + 1 :]:
            assert (
                a.x + a.length <= b.x + 1e-6
                or b.x + b.length <= a.x + 1e-6
                or a.y + a.width <= b.y + 1e-6
                or b.y + b.width <= a.y + 1e-6
            ), (a, b)


def test_block_packer_finds_full_grid_that_greedy_missed():
    chep = Pallet.from_standard("CHEP")

    assert maximize_case_count(chep, Case("A", 8, 5, 5))[0] == 48
    assert maximize_case_count(chep, Case("B", 12, 10, 8))[0] == 16
    assert maximize_case_count(chep, Case("C", 11, 9, 5))[0] >= 18


def test_layers_never_overlap_or_leave_the_deck_across_case_sizes():
    chep = Pallet.from_standard("CHEP")
    for length in range(3, 20, 2):
        for width in range(3, length + 1, 2):
            count, result = maximize_case_count(chep, Case("S", length, width, 5))
            assert count == len(result.placements)
            _assert_valid_layer(chep, result.placements)


def test_partial_load_is_valid_and_reports_unplaced_cases():
    pallet = Pallet(length=40, width=48, unit="in")
    result = solve_pallet_layout(pallet, [Case("P", 8, 5, 5, quantity=50)])

    assert not result.feasible
    assert len(result.placements) == 48
    assert len([v for v in result.violations if "No feasible footprint" in v]) == 2
    _assert_valid_layer(pallet, result.placements)
