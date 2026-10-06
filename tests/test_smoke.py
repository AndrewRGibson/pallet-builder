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

    # 10 per layer, and 2-high cases stack twice within the 5-high build.
    assert max_count == 20
    assert result.feasible
    assert (result.layers, result.cases_per_layer) == (2, 10)


def test_maximize_case_count_handles_single_positive_fit_without_zero_quantity_search():
    pallet = Pallet(length=10, width=8, height=5, unit="in", max_weight=2000)
    case = Case("A", 9, 5, 2, weight=100, unit="in")

    max_count, result = maximize_case_count(pallet, case)

    assert max_count == 2
    assert result.feasible
    assert result.cases_per_layer == 1


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

    # A 12in build height leaves 6in above the 6in deck: too low for an 8in case.
    capped = Pallet.from_standard("CHEP", unit="in", max_build_height=12)
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
            # Block packer geometry only; the GA has its own tests below.
            count, result = maximize_case_count(chep, Case("S", length, width, 5), optimize=False)
            assert count == len(result.placements)
            _assert_valid_layer(chep, result.placements)


def test_partial_load_is_valid_and_reports_unplaced_cases():
    pallet = Pallet(length=40, width=48, unit="in")
    result = solve_pallet_layout(pallet, [Case("P", 8, 5, 5, quantity=50)])

    assert not result.feasible
    assert len(result.placements) == 48
    assert len([v for v in result.violations if "No feasible footprint" in v]) == 2
    _assert_valid_layer(pallet, result.placements)


def _assert_valid_load(pallet, placements):
    for p in placements:
        assert p.x >= -1e-9 and p.y >= -1e-9 and p.z >= -1e-9
        assert p.x + p.length <= pallet.length + 1e-6 and p.y + p.width <= pallet.width + 1e-6
    for i, a in enumerate(placements):
        for b in placements[i + 1 :]:
            assert (
                a.x + a.length <= b.x + 1e-6
                or b.x + b.length <= a.x + 1e-6
                or a.y + a.width <= b.y + 1e-6
                or b.y + b.width <= a.y + 1e-6
                or a.z + a.height <= b.z + 1e-6
                or b.z + b.height <= a.z + 1e-6
            ), (a, b)


def test_layers_fill_build_height_including_deck():
    # 60in build height - 6in CHEP deck = 54in for cases: six 8in layers of 16.
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    max_count, result = maximize_case_count(chep, Case("L", 12, 10, 8, weight=10))

    assert (max_count, result.layers, result.cases_per_layer, result.max_layers) == (96, 6, 16, 6)
    assert result.feasible
    assert max(p.z + p.height for p in result.placements) == 48
    _assert_valid_load(chep, result.placements)


def test_every_layer_has_a_flat_top():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    for this_side_up in (True, False):
        _, result = maximize_case_count(chep, Case("F", 15, 11, 7, this_side_up=this_side_up))
        by_layer = {}
        for p in result.placements:
            by_layer.setdefault(p.z, set()).add(p.height)
        assert all(len(heights) == 1 for heights in by_layer.values()), by_layer


def test_tipping_picks_the_orientation_that_stacks_most():
    # Upright, a 30in-tall case can't fit in the 20in above the deck; tipped, 10in layers stack twice.
    pallet = Pallet(length=40, width=48, height=26, deck_height=6, unit="in")
    upright, _ = maximize_case_count(pallet, Case("T", 10, 10, 30))
    tipped, result = maximize_case_count(pallet, Case("T", 10, 10, 30, this_side_up=False))

    assert upright == 0
    assert tipped > 0 and result.layers == 2
    assert all(p.height == 10 for p in result.placements)
    _assert_valid_load(pallet, result.placements)


def test_weight_limit_leaves_a_partial_top_layer():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    chep.max_weight = 200
    max_count, result = maximize_case_count(chep, Case("W", 12, 10, 8, weight=10))

    assert max_count == 20
    assert (result.layers, result.cases_per_layer) == (2, 16)
    _assert_valid_load(chep, result.placements)


def test_build_height_must_exceed_deck_height():
    import pytest

    with pytest.raises(ValueError, match="deck height"):
        Pallet.from_standard("CHEP", unit="in", max_build_height=6)


def test_ga_beats_block_packer_with_interlocking_layer():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    case = Case("G", 9, 7, 6)

    block_count, block = maximize_case_count(chep, case, optimize=False)
    ga_count, ga = maximize_case_count(chep, case)

    assert block.cases_per_layer == 27
    assert ga.cases_per_layer == 28
    assert ga_count == 28 * ga.max_layers > block_count
    _assert_valid_load(chep, ga.placements)

    runs = {run.solver: run for run in ga.solver_runs}
    assert runs["Genetic algorithm"].selected and not runs["Block packer"].selected
    assert runs["Genetic algorithm"].target == 30  # malleable bound: 1920 / 63 per layer
    best = [entry[1] for entry in runs["Genetic algorithm"].history]
    assert best == sorted(best)  # elitism: the best objective never gets worse
    assert all(entry[2] <= entry[1] for entry in runs["Genetic algorithm"].history)


def test_ga_reaches_the_bound_and_stops_early():
    chep = Pallet.from_standard("CHEP", unit="in")
    # Column stacking: the objective is the case count alone, so the optimum is exactly the bound.
    _, result = maximize_case_count(chep, Case("G", 19, 7, 6), stacking="column")
    run = next(run for run in result.solver_runs if run.solver == "Genetic algorithm")

    assert run.cases_per_layer == run.target == 14
    assert run.history[-1][1] == 14  # objective = placed - unplaced, so the optimum is the bound
    assert len(run.history) - 1 < 40


def test_ga_is_skipped_when_block_packer_hits_the_bound():
    chep = Pallet.from_standard("CHEP", unit="in")
    _, result = maximize_case_count(chep, Case("B", 8, 5, 5))
    runs = {run.solver: run for run in result.solver_runs}

    assert runs["Block packer"].selected and runs["Block packer"].cases_per_layer == 48
    assert not runs["Genetic algorithm"].ran
    assert "already reaches the bound" in runs["Genetic algorithm"].note


def test_volume_bound_assumes_malleable_cases():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    _, result = maximize_case_count(chep, Case("V", 12, 10, 8))

    assert result.volume_bound == (40 * 48 * 54 // (12 * 10 * 8))  # 108


def _layer_xy(result, layer_number):
    z_values = sorted({p.z for p in result.placements})
    return sorted((round(p.x, 6), round(p.y, 6), p.length, p.width)
                  for p in result.placements if p.z == z_values[layer_number])


def test_interlock_never_costs_cases_and_respects_min_support():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    for length, width in [(9, 7), (12, 10), (8, 5), (11, 9), (14, 9)]:
        case = Case("I", length, width, 8)
        column, _ = maximize_case_count(chep, case, stacking="column")
        interlock, result = maximize_case_count(chep, case, stacking="interlock", min_support=0.7)
        assert interlock == column, (length, width)
        assert result.min_support >= 0.7 - 1e-9, (length, width, result.min_support)
        _assert_valid_load(chep, result.placements)


def test_interlocked_layers_alternate_a_flipped_pattern():
    from pallet_builder.solver import FLIP_LABELS

    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    _, result = maximize_case_count(chep, Case("I", 9, 7, 8), stacking="interlock")

    assert result.flip in FLIP_LABELS and result.flip != "none"
    assert result.interlock > 0.5
    assert _layer_xy(result, 0) == _layer_xy(result, 2)  # odd layers share pattern A
    assert _layer_xy(result, 0) != _layer_xy(result, 1)  # even layers use the flipped pattern B
    _assert_valid_load(chep, result.placements)


def test_column_stacking_repeats_one_pattern():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    _, result = maximize_case_count(chep, Case("C", 9, 7, 8), stacking="column")

    assert result.flip == "none" and result.interlock == 0
    assert all(_layer_xy(result, i) == _layer_xy(result, 0) for i in range(result.layers))


def test_no_column_stacking_falls_back_to_one_layer_when_nothing_interlocks():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    count, result = maximize_case_count(chep, Case("N", 9, 8, 8), stacking="no_column")

    assert result.layers == 1 and count == result.cases_per_layer
    assert "Column stacking is disallowed" in result.stacking_note


def test_no_column_keeps_full_count_when_an_interlocking_pattern_exists():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    case = Case("N", 7, 4, 8)
    interlock, _ = maximize_case_count(chep, case, stacking="interlock")
    no_column, result = maximize_case_count(chep, case, stacking="no_column")

    assert no_column == interlock
    assert result.interlock > 0 and not result.stacking_note


def test_stacking_options_are_validated():
    import pytest

    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    with pytest.raises(ValueError, match="stacking"):
        maximize_case_count(chep, Case("V", 9, 7, 8), stacking="pyramid")
    with pytest.raises(ValueError, match="min_support"):
        maximize_case_count(chep, Case("V", 9, 7, 8), min_support=1.5)


def test_solver_runs_report_work_and_time():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    _, result = maximize_case_count(chep, Case("T", 9, 7, 8))
    runs = {run.solver: run for run in result.solver_runs}

    assert runs["Block packer"].iterations > 0 and runs["Block packer"].evaluations > 0
    assert runs["Genetic algorithm"].iterations == len(runs["Genetic algorithm"].history) - 1
    assert runs["Genetic algorithm"].evaluations > 0
    assert all(run.elapsed_ms >= 0 for run in result.solver_runs)


def test_sensitivity_insights_ladder_risks_and_no_gain():
    from pallet_builder.insights import Variant, sensitivity_insights

    base = Variant(9, 7, 8, cases=168, ti=28, hi=6)
    variants = [
        Variant(8.75, 7, 8, cases=174, ti=29, hi=6),    # small gain, smallest change
        Variant(9, 7, 7.5, cases=196, ti=28, hi=7),     # an extra layer
        Variant(8.75, 7, 7.5, cases=196, ti=28, hi=7),  # same gain as above with a bigger change: dominated
        Variant(9.25, 7, 8, cases=162, ti=27, hi=6),    # length up loses a case per layer
        Variant(9, 7.5, 8, cases=150, ti=25, hi=6),
    ]
    insights = sensitivity_insights(base, variants, "in")
    gains = [i for i in insights if i.kind == "gain"]
    risks = [i for i in insights if i.kind == "risk"]

    assert [g.variant.cases for g in gains] == [174, 196]  # ladder: smallest change first, dominated dropped
    assert "reduce the length by 0.25 in (9 \u2192 8.75)" in gains[0].text
    assert "+6 cases (+4% case density)" in gains[0].text and "Ti 28 \u2192 29" in gains[0].text
    assert "1 more layer (Hi 6 \u2192 7)" in gains[1].text
    assert {r.variant.cases for r in risks} == {162, 150}
    assert any("Watch the length tolerance" in r.text and "loses 6 cases" in r.text for r in risks)

    none = sensitivity_insights(base, [Variant(9.25, 7, 8, cases=162, ti=27, hi=6)], "in")
    assert none[0].kind == "info" and "No size change" in none[0].text


def test_sensitivity_insights_flag_weight_cap():
    from pallet_builder.insights import Variant, sensitivity_insights

    base = Variant(12, 10, 8, cases=96, ti=16, hi=6)
    taller_stack = Variant(12, 10, 7.6, cases=110, ti=16, hi=7)  # space for 112, weight caps at 110
    (gain,) = sensitivity_insights(base, [taller_stack], "in", max_weight=2200, case_weight=20)
    assert "Max weight caps it at 110; the space would take 112" in gain.text


def test_ga_stops_after_stalling_and_reports_why():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    case = Case("S", 9, 7, 8)

    _, fixed = maximize_case_count(chep, case, optimization_generations=40)
    _, stalled = maximize_case_count(chep, case, optimization_generations=500, optimization_stall=15)
    fixed_ga = next(r for r in fixed.solver_runs if r.solver == "Genetic algorithm")
    stalled_ga = next(r for r in stalled.solver_runs if r.solver == "Genetic algorithm")

    assert fixed_ga.iterations == 40 and "generation limit (40)" in fixed_ga.note
    assert stalled_ga.iterations < 500 and "no improvement for 15 generations" in stalled_ga.note
    best = [entry[1] for entry in stalled_ga.history]
    last_gain = max(i for i in range(len(best)) if i == 0 or best[i] > best[i - 1])
    assert len(best) - 1 - last_gain == 15  # stopped exactly 15 generations after the last improvement


def test_ga_stall_must_not_be_negative():
    import pytest

    with pytest.raises(ValueError, match="optimization_stall"):
        maximize_case_count(Pallet.from_standard("CHEP"), Case("S", 9, 7, 8), optimization_stall=-1)


def _layer_gaps(pallet, result, layer_number):
    z_values = sorted({p.z for p in result.placements})
    layer = [p for p in result.placements if p.z == z_values[layer_number]]
    return (round(min(p.x for p in layer), 6), round(pallet.length - max(p.x + p.length for p in layer), 6),
            round(min(p.y for p in layer), 6), round(pallet.width - max(p.y + p.width for p in layer), 6))


def test_centred_alignment_keeps_every_layer_centred():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    _, result = maximize_case_count(chep, Case("C", 14, 9, 8), alignment="center")

    assert result.alignment == "center" and result.interlock > 0
    for layer in range(result.layers):
        left, right, front, back = _layer_gaps(chep, result, layer)
        assert left == right and front == back, (layer, left, right, front, back)
    _assert_valid_load(chep, result.placements)


def test_corner_alignment_keeps_every_layer_flush_to_two_sides():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    _, result = maximize_case_count(chep, Case("C", 9, 7, 8), alignment="corner")

    assert result.flip != "none"  # flipped layers, yet still in the same corner
    assert {_layer_gaps(chep, result, layer)[0::2] for layer in range(result.layers)} == {(0.0, 0.0)}
    _assert_valid_load(chep, result.placements)


def test_alternate_alignment_moves_flipped_layers_to_the_opposite_side():
    chep = Pallet.from_standard("CHEP", unit="in", max_build_height=60)
    _, result = maximize_case_count(chep, Case("C", 9, 7, 8), alignment="alternate")

    a_left, a_right, *_ = _layer_gaps(chep, result, 0)
    b_left, b_right, *_ = _layer_gaps(chep, result, 1)
    assert (a_left, a_right) == (0.0, 1.0) and (b_left, b_right) == (1.0, 0.0)
    _assert_valid_load(chep, result.placements)


def test_alignment_is_validated():
    import pytest

    with pytest.raises(ValueError, match="alignment"):
        maximize_case_count(Pallet.from_standard("CHEP"), Case("A", 9, 7, 8), alignment="diagonal")
