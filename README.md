# Pallet Builder

Pallet Builder works out how many identical cases fit on a pallet, and exactly how to stack them, within the pallet's weight rating and a maximum build height. Each run is intentionally scoped to a single case type: one SKU, one fixed case size, repeated as many times as fits.

## Quick start

```bash
uv sync                          # install dependencies (Python 3.13+)
uv run streamlit run app.py      # open the planner UI at http://localhost:8501
uv run pytest                    # run the test suite
```

The solver packs each layer with block patterns (improved by a genetic algorithm where they fall short), stacks flat layers up to the max build height (which includes the pallet deck), and interlocks alternate layers where it can. See [Current solver behavior](#current-solver-behavior) and [Streamlit UI](#streamlit-ui) for details.

**Versioning:** the version is `0.1.<commit count>`. `pallet_builder.__version__` and the app header read the count from git, so they stay current automatically. The static `version` in `pyproject.toml` (used for packaging) must be bumped to the new count in every commit.

## Background

The operations-research background (problem framing, integer programming, CP-SAT, genetic algorithms, decomposition, and the constraints and goals a full solution should consider) is in [docs/background.md](docs/background.md).

## Recommended approach for this project

A sensible phased strategy is:

1. Exact geometry and feasibility: first constrain the problem to 2D footprint packing for a fixed layer height.
2. Single-layer heuristic: pack cases in a guillotine or shelf-style arrangement, optimize for minimal waste and overhang.
3. Layer assignment: group cases into layers, then ensure height, weight, and vertical stability constraints are met.
4. Stacking logic: allow only legal stacks or columns and enforce stability checks.
5. Metaheuristic improvement: run a GA or local-search improvement loop atop a feasible layout to reduce waste or improve placement symmetry.

This repo implements steps 1–3 and part of step 5 for a single repeated case type:
- an exact-geometry block packer for each layer,
- a GA layer search that improves on it where it falls short of the bound or where a better-interlocking pattern exists,
- flat layers stacked up to the max build height within the weight and other load limits,
- column or interlocked stacking (alternate layers flipped), with a minimum-support rule.

Still open: load stability checks beyond support (center of gravity, crush limits).

## Current solver behavior

### Layer pattern

Two solvers can build a layer. The solver keeps whichever layer holds more cases, and on a tie, whichever interlocks better (see [Stacking](#stacking-column-or-interlocked)).

**Block packer.** A recursive guillotine search over the deck: each region is either filled with a uniform grid of one case orientation or cut in two, and each half is solved the same way. It finds the classic block patterns. For example, 5×8 cases on a 40×48 deck give the full 48, where a simple greedy packer manages 45. When the search space is very large (tiny cases on a big deck), it is limited to two-block patterns so it stays responsive.

**GA layer search** (genetic algorithm). It starts from the **malleable bound**: how many cases would fit if they could be squeezed into any shape. For a whole pallet that's the space above the deck divided by the case volume. Because layers are flat and identical, this works out to `floor(deck area / case footprint)` per layer, which is the GA's target.
- **Encoding:** a chromosome has one gene per case up to the target, and each gene picks that case's orientation.
- **Decoding:** cases are placed in order at the bottom-left-most free spot, which can produce interlocking (non-guillotine) patterns that the block packer can't.
- **Objective:** `placed − penalty × unplaced`, so the bound itself is the optimum.
- **Search:** two-point crossover, point and block mutation, tournament selection and elitism. It stops early at the bound.
- **When it runs:** when the block packer falls short of the bound, or when layers stack and the block pattern doesn't fully interlock (the GA may find an equally dense pattern that interlocks better). It's skipped when the footprint is square (only one orientation) or the target is over 150 cases per layer.
- **Example:** for 9×7 cases on CHEP it finds 28 per layer, where the block packer finds 27 (the bound is 30). Defaults are 40 generations, population 24, seed 0, so results are reproducible.
- **Stopping:** the GA always stops on reaching the bound. Otherwise it runs either a fixed number of generations (the default) or, with `optimization_stall=N` ("No improvement" in the app), until its best objective hasn't improved for N generations, with `optimization_generations` as the upper limit (up to 2,000 in the app). Each run's note gives the stopping reason: reached the bound, no improvement, or the generation limit.

### Layers and build height

- `Pallet.height` is the **max build height measured from the floor, including the pallet**. The space for cases is `height − deck_height`. For example, a 60" build on a 6" CHEP deck leaves 54".
- **Every layer has a flat top.** All cases in a layer share the same upright dimension, so the number of layers is `floor((max build height − deck height) / layer height)`. Layers use one pattern (A), with every other layer flipped (B) when stacking interlocks. A partial top layer, which happens when the weight limit or quantity runs out first, fills in pattern order.
- Cases marked *this side up* (the default) only rotate flat on the deck. With `this_side_up=False`, the solver tries each dimension as the upright one and keeps the option that stacks the most cases in total. Ties go to more cases per layer, for a wider base.
- With `height=None`, there is no build limit and the solver builds a single layer.

### Limits

`max_weight` caps the total case weight, `max_volume` caps the total case volume, and `max_plan_area` caps the combined case footprint. `maximize_case_count` takes the smaller of layers × cases per layer and those caps. A run that breaks a limit is reported as infeasible, with a reason for each limit it breaks.

### Stacking: column or interlocked

Repeating one pattern in every layer stacks the cases in columns, which are weak because every seam runs the full height. The `stacking` option controls this:

| Mode | Behavior |
|---|---|
| `"interlock"` (default) | Alternate layers use the pattern's best **flip**: mirrored along the length, mirrored along the width, or rotated 180°. Flipping is chosen only when it makes cases bridge the seams below. It never costs a case: the count is maximized first, and interlock only breaks ties. |
| `"column"` | Every layer uses the same pattern. |
| `"no_column"` | Interlock is required. The GA first searches on the normal objective; if its best pattern can't interlock, a second pass penalizes non-interlocking patterns and may trade cases for interlock. If nothing interlocks, the load is limited to one layer and `stacking_note` says why. |

How it's measured:
- **Interlock** is the share of cases resting on two or more cases in the layer below, where each support carries at least 10% of the case.
- **Support** is the share of a case's base that rests on cases below. A flip is only allowed if every case keeps at least `min_support` (default 0.7). This stops a flip from leaving cases hanging over a gap at the pallet edge.
- **Example:** across 209 case sizes on CHEP at 60", interlocking (without losing cases) was found for 172. Flipping the block pattern was enough for 60; the GA found an interlocking pattern for 112.

### Solver log

Every result records what each solver did in `LayoutResult.solver_runs`, a list of `SolverRun` entries:
- solver name, layer family (e.g. "8 in tall layers"), cases per layer and the bound,
- whether the solver ran or was skipped (with the reason), and whether its layer was used,
- the chosen flip and interlock,
- work done: `iterations` (block packer: region states solved; GA: generations) and `evaluations` (block packer: cuts tried; GA: distinct patterns decoded), plus `elapsed_ms`, measured on the first solve since results are cached,
- for the GA, a `(generation, best objective, mean objective, best interlock)` history.

### API

- `Case`: dimensions, weight, quantity, unit, and `this_side_up`.
- `Pallet`: deck length and width, `height` (max build height including the deck), `deck_height`, unit, and optional `max_weight`, `max_volume` and `max_plan_area`. `Pallet.from_standard(name, unit=..., max_build_height=...)` loads the CHEP, GMA, EUR_1200X800 and EUR_1000X1200 presets, and "EURO" is an alias for EUR_1200X800. Preset max weights are in lb for CHEP/GMA and kg for EUR. `Pallet` doesn't store a weight unit, so case weights must use the same unit.
- `solve_pallet_layout(pallet, cases, optimize=True, optimization_generations=40, optimization_population=24, optimization_seed=0, optimization_stall=0, stacking="interlock", min_support=0.7)`: places the given cases and returns a `LayoutResult`. Pass `optimize=False` to use the block packer only. `optimization_stall=N` stops the GA after N generations without improvement (0 = run a fixed number of generations).
- `maximize_case_count(pallet, case, optimize=True, ..., stacking="interlock", min_support=0.7)`: returns the largest count that fits, with its `LayoutResult`. It takes the same options.
- `optimize_layout(pallet, cases, generations=..., population_size=..., seed=..., stall=...)`: shorthand for `solve_pallet_layout` with the GA on.
- `pallet_builder.inputs`: read, write and validate `.pallet` input files (see [Input files](#streamlit-ui)).
- `pallet_builder.insights.sensitivity_insights`: opportunities and risks from a set of solved case sizes.
- `LayoutResult` contains:
  - `placements`: x, y, z, size and orientation for each case, with z measured from the top of the deck.
  - `feasible` and `violations`.
  - `layers`, `cases_per_layer` and `max_layers`. Capacity is `max_layers × cases_per_layer`.
  - `utilization`: deck coverage of the base layer.
  - `volume_utilization`: case volume as a share of the space above the deck.
  - `volume_bound`: the malleable bound for the whole pallet.
  - `stacking`, `flip`, `interlock`, `min_support` and `stacking_note`: how the layers are stacked.
  - `solver_runs`: the solver log.
  - `total_weight`.

Example:

```python
from pallet_builder import Case, Pallet, maximize_case_count, solve_pallet_layout

pallet = Pallet.from_standard("CHEP", unit="in", max_build_height=60)  # 54in above the 6in deck
case = Case("Widget", length=8, width=5, height=6, weight=4, unit="in")

count, layout = maximize_case_count(pallet, case)
print(count, layout.layers, layout.cases_per_layer)  # 432 9 48

result = solve_pallet_layout(pallet, [Case("Widget", 8, 5, 6, weight=4, quantity=100)])
print(result.feasible, result.layers)  # True 3  (two full layers + a top layer of 4)
```

## Streamlit UI

Run it with:

```bash
uv run streamlit run app.py
```

The page has the title and version at the top, then one row of tabs: **Overview, Input, Summary, 3D view, Placements, By iteration, Sensitivity**. It opens on Overview, and the title and tab row stay pinned at the top while you scroll. The app finds the most cases that fit.

- **Solving:** with **Auto-solve** on (the default), the app re-solves whenever an input changes. Turn it off for heavy settings, such as large GA runs, and press **Solve** when ready. A note says when the inputs have changed since the last solve.
- **Speed:** the heavier tabs (3D view, Placements, By iteration, Sensitivity) only compute while they're open, so an edit costs about 0.1 s on the Summary tab even with sensitivity on.
- **Result strip:** a one-line result at the top of the Input tab (cases, layers × per layer, cube use, and what limits the count) shows the effect of each edit without switching tabs.

Every input that affects the solve is on the **Input** tab. It's laid out in three columns (Units and Pallet; Build and Case; Solve), with each label and value on one line:

- **Units**: one system for every length and weight, either US (in, lb) or Metric (cm, kg). Switching converts every value already entered.
- **Pallet**:
  - Preset (CHEP, GMA, EUR 1200×800, EUR 1000×1200, converted to the active units) or custom dimensions.
  - Deck height, and max weight (the pallet's rating).
  - Choosing a preset fills these in, plus a typical build height (60 in or 180 cm). Editing a pallet dimension switches the preset to "Custom".
- **Build**: limits for this load that don't depend on the pallet choice: max build height (from the floor, including the pallet), max volume and max plan area.
- **Optional limits**: a blank field means no limit, and 0 is a real limit. For example, a max weight of 0 means no case fits, and the app explains why.
- **Case**: length, width, height and weight, plus *This side up*.
- **Solve**:
  - Stacking: interlock when possible, column, or no column stacking; plus the minimum support.
  - The GA layer search switch, with its stop rule (fixed generations, or stop after no improvement for N generations with a max), generations, population and seed.
  - Settings that don't apply are greyed out rather than hidden, so their values are kept.

**Input files.** The bar at the top of the Input tab loads a sample, resets to the defaults, opens a saved file, or saves the current inputs. If the Name is blank, the file is named from the inputs (e.g. "CHEP 12x10x8 in"). The same file can be opened again after edits.

- **Format:** a `.pallet` file is JSON. `"format": "pallet-builder-input"` and a `"version"` number mark it as a Pallet Builder file, so other JSON files are rejected clearly. Lengths and weights are in the file's own `"units"` ("US" in/lb, or "Metric" cm/kg).
- **Contents:** it records everything on the Input tab (units, pallet, build limits, case, stacking, GA and sensitivity settings), plus a name and description. A blank limit is saved as `null`, which means no limit; `0` stays a real limit.
- **Partial files:** any section or field left out falls back to the defaults, so a hand-written file only needs the values that differ.
- **Errors:** an invalid file is rejected with the first problem it finds, e.g. "case.length must be at least 0.001".
- **Samples:** the `samples/` folder holds the worked examples, always listed in the app. They cover:
  - the CHEP default,
  - a full grid,
  - a GA-plus-interlock case,
  - the no-column fallback,
  - a weight-limited load,
  - a tipped tall case,
  - a footprint that only fits rotated,
  - a metric EUR pallet,
  - an infeasible build,
  - column stacking that reaches the bound.
- **Samples as tests:** each sample records its `"expected"` result, and `tests/test_inputs.py` solves every one, so the samples double as regression tests. Add a scenario by dropping in another `.pallet` file with its expected result.
- **Code:** reading, writing and validation live in `pallet_builder.inputs`. `load`/`loads` validate and fill defaults, `dumps` writes a file, and `solver_arguments` turns a document into `Pallet`, `Case` and solve options.

The other tabs:

- **Overview**: what the app is for, how to use the Input tab, how the solver works, and what each tab shows.
- **Summary**:
  - **Metrics:** cases, layers (e.g. "6 layers × 16"), max by volume (the cases that would fit if they filled the space perfectly), cube use, deck coverage, load weight, build height (deck + load), headroom, interlock and minimum support. Interlock reads "none found" when it was tried but no flip keeps every case supported, and "n/a" when it doesn't apply.
  - **Solver notes:** the solver limits that applied to this result:
    - the GA skipped because a layer would hold over 150 cases,
    - the block packer limited to two-block patterns on a large deck,
    - the GA stopping at its generation limit below the bound,
    - tipping using one upright side for the whole load,
    - each layer using a single pattern.
  - **Limit:** what stops the count going higher (pallet space, max weight, max volume or max plan area), or why a run is infeasible. A caption names the stacking and flip, e.g. "even layers rotated 180°".
  - **Solver status:** a table of every solver run, with the solve time (or "cached" when the result was reused). It lists layer family, cases per layer, the bound, interlock, iterations, evaluations, time, whether the run was used, and notes such as why the GA was skipped. Solver and Layers stay pinned when scrolling.
- **3D view**: an interactive Plotly model of the built pallet.
  - Drag to spin (turntable rotation, so the pallet stays upright), scroll to zoom, and use the Iso, Front, Side and Top buttons to reset the viewpoint.
  - The deck is brown, layers alternate shades, and red dashes mark the max build height.
  - Loads over 6,000 cases are drawn as one block per layer.
- **Placements**: the layer, pattern (A or flipped B), x/y/z and size for each case.
- **By iteration**: the GA's best and mean objective per generation, plus best interlock on a second axis when stacking interlocks. The bound and the block packer's score are drawn as reference lines.
- **Sensitivity**: re-solves every combination of case-size changes. Each of length, width and height is either left unchanged or moved by one of its own steps, independently of the others.
  - **Settings table:** each dimension has its own on/off, change type (a fixed amount to 2 decimal places, default 0.20 in / 0.50 cm, or a percentage, default 2%), step size, and 1–3 steps each way (default 1).
  - **Opportunities and risks:** plain-language findings computed from the results, so every number can be checked against the table.
    - **Gains** read as a ladder, from the smallest change that adds cases to the largest gain. Each one says where the gain comes from (more cases per layer, more layers, or both) and flags when max weight rather than space caps it. For example: "If you can reduce the length by 0.25 in (9 → 8.75), the pallet holds 174 cases instead of 168: +6 cases (+4% case density), from 1 more case per layer (Ti 28 → 29)."
    - **Risks** give, for each dimension, the smallest change that loses cases, i.e. how tight its tolerance must be.
    - The logic is in `pallet_builder.insights` (`sensitivity_insights`), so it can also feed a future AI-written summary.
  - **Runs:** (2n+1)³ − 1 for n steps on all three dimensions: 26 at 1 step, up to 342 at 3. A progress bar shows the run. Steps that would take a dimension to zero or below are skipped and listed.
  - **Results:** for each combination, the change to each dimension ("–" when unchanged), the case size, cases and the change from the base, Ti (cases per layer) and Hi (layers), deck coverage, cube use and interlock. Case counts and percentage columns are drawn as in-cell bars.
  - **Order:** the base case is highlighted at the top, and the combinations follow, ranked by fitness: most cases, then cube use, interlock and deck coverage.

**Export:** every table can be downloaded as CSV from its own toolbar (hover over the table).

### Code layout and tests

- `src/pallet_builder/`: the solver (`solver.py`), input files (`inputs.py`) and sensitivity insights (`insights.py`). No Streamlit dependency.
- `app.py`: assembles the page.
- `ui/` (beside `app.py`): the Streamlit UI, one module per area:
  - `state.py`: session state, units and `.pallet` mapping,
  - `files.py`: the file bar,
  - `inputs_tab.py`,
  - `solving.py`: cached solve and explanations,
  - `results.py`: Overview, Summary, Placements and By iteration,
  - `view3d.py`,
  - `sensitivity.py`,
  - `style.py`: CSS.
- `tests/`: `test_smoke.py` covers the solver, `test_inputs.py` covers file handling and every sample, and `test_app.py` runs the app headlessly (Streamlit's `AppTest`). The app tests cover every sample loading in the app, the save/load round trip, unit switching, settings that must keep their values, Auto-solve, lazy tabs, Reset and error handling.
- **Streamlit version:** the compact Input layout styles some of Streamlit's internal element IDs, so `pyproject.toml` pins Streamlit to 1.65.x. A test checks the IDs still exist before you raise the pin.

## Recommendations for future versions

- **More interlock options**: patterns that alternate between two different layouts (not just flips), and user-set interlock targets.
- **Exact layer bounds**: the GA narrows the gap to the malleable bound but can't prove optimality. An exact 2D solver (for example CP-SAT) could certify the best layer for awkward case sizes.
- **Stability checks**: center-of-gravity and load-distribution checks, and a per-case crush or max-stack-weight limit.
- **Weighted objective**: tunable coefficients to trade density against stability, beyond the current count-first ranking.
- **Mixed loads**: support for more than one case type per pallet.
- **Export**: printable loading instructions (a layer sheet per pattern) alongside the CSV tables and `.pallet` input files.

## Summary

This is a real-world rectangular packing problem with strong operational constraints. The project deliberately handles one case type per pallet run, which keeps the model easy to reason about, validate and present. Within that scope, it packs each layer with block patterns, improves on them with a GA that targets the malleable bound, stacks flat layers to the max build height (interlocked by flipping alternate layers where that helps), respects weight, volume and area limits, explains what limits each result and which solver produced it, shows the built pallet in an interactive 3D view, runs a case-size sensitivity analysis with plain-language opportunities, and saves and loads complete input sets as `.pallet` files.
