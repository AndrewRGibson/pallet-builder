# Pallet Builder

This project is a practical starting point for a pallet-loading optimizer. For this phase, each run is intentionally scoped to stacking a single case type on a pallet: one SKU, one fixed case dimension set, repeated as many times as needed to fill the pallet.

## Quick start

```bash
uv sync                          # install dependencies
uv run streamlit run app.py      # open the planner UI (3D view, layer plan, export)
uv run pytest                    # run the test suite
```

The solver packs each layer with exact block patterns and stacks flat layers up to the max build height, including the pallet deck. See [Current solver behavior](#current-solver-behavior) and [Streamlit UI](#streamlit-ui) for details.

**Versioning:** the version is `0.1.<commit count>`. `pallet_builder.__version__` and the app header read the count from git, so they stay current automatically. The static `version` in `pyproject.toml` (used for packaging) must be bumped to the new count in every commit.

## Problem framing

A pallet build is effectively a constrained packing problem. In its simplest form it is a 2D rectangular packing problem on the pallet footprint, with a 3D extension once stacking height, stability, and load limits are included. Because this version is intentionally single-case, the optimization problem is narrowed to arranging repeated copies of the same case type efficiently while respecting physical, operational, and safety constraints.

The optimization problem still involves:

- maximizing pallet utilization
- minimizing wasted area and empty gaps
- reducing overhang and underhang
- keeping the load within height, width, and length tolerances
- respecting weight limits and center-of-gravity limits
- avoiding unstable stacks and unsafe overhangs
- preserving handling constraints such as forklift access and stretch-wrap requirements
- optionally favoring brick-wall patterns or avoiding stacked columns when the product is fragile

The ideal objective is not a single scalar value. In practice the optimizer should minimize a weighted penalty function such as:

- footprint utilization loss
- overhang penalty
- void-space penalty
- stack instability penalty
- center-of-gravity deviation penalty
- handling and operational constraints penalty

The user can then tune the trade-off between density and safety.

## Operations Research methods

### 1. Integer programming (IP)

For a fixed set of case dimensions and a fixed pallet footprint, MIP is often the most defendable formulation when the problem is discretized well enough. The usual approach is to identify candidate placements in a grid or on candidate rectangles, then introduce binary decision variables for whether a case is placed in a given position and orientation.

Typical constraints include:

- non-overlap across rectangles in the same layer
- footprint containment within pallet dimensions
- orientation restrictions (e.g., only 90-degree rotations)
- no placement across pallet edges unless overhang is explicitly allowed
- layer-by-layer volume and height constraints
- stacking compatibility constraints for cases that may be stacked safely

Advantages:

- exact optimality on a finite discretization
- explicit modeling of hard constraints
- good auditability and explainability for business users

Drawbacks:

- scales poorly with large numbers of cases or many possible placements
- very sensitive to the number of candidate positions
- difficult to model full 3D stability and dynamic load propagation

### 2. CP-SAT / constraint programming

Constraint programming is often a better fit when the constraints are highly logical and combinatorial, such as:

- a case must not overlap any placed case
- a stack must use a legal pattern
- case orientations are restricted
- some cases must remain on the ground while others may stack
- identical cases may be grouped into columns

CP-SAT is also useful for a layered decomposition: assign cases to layers first, then solve the 2D packing problem within each layer. This hybrid approach is often more tractable than a full 3D MIP.

### 3. Genetic algorithms and metaheuristics

For a single-case pallet run, a GA is still useful as a search layer. A GA is especially helpful when:

- the pallet footprint is constrained and close to full
- objective trade-offs are noisy or difficult to linearize
- the solution space contains many near-feasible layouts
- there is a need to quickly generate strong candidate layouts for interactive use

A GA can evolve:

- ordering of placement for repeated cases
- orientation choices for the case type
- anchor-point and shelf-positioning heuristics
- layer or column grouping decisions when needed
- stacking support decisions for legal load patterns

The evaluation function usually approximates the real objective with penalty terms for overlap, overhang, voids, and stability violations.

Advantages:

- flexible and easy to extend
- handles non-linear objectives naturally
- good at producing strong practical layouts quickly

Drawbacks:

- no guarantee of global optimality
- difficult to certify feasibility to customers
- sensitive to representation and mutation operators

### 4. Column generation, branch-and-bound, and layered decomposition

Many industrial palletizers rely on decomposition:

- Step 1: choose a set of candidate layers or columns
- Step 2: pack each layer as a 2D container problem
- Step 3: combine layers while respecting height and weight limits

This is a strong strategy when the pallet height is limited and there are repeated case types. It can combine the tractability of specialized packers with exact optimization for the upper layer assignment.

### 5. Beam search and greedy constructive heuristics

This is often the most operationally useful method in real-time systems. A constructive heuristic keeps adding case placements while evaluating candidate expansions by objective and constraint slack. This approach is particularly useful when a fast estimate is needed before a harder optimization pass is run.

## Constraints and restrictions to consider

Before building the application, the following should be specified carefully:

- pallet dimensions: length, width, height, deck board style, edge clearance
- case dimensions: length, width, height, tolerance, variation between units
- case weights and center-of-mass data
- maximum pallet load and axle/vehicle stacking limits
- allowable overhang and underhang values
- whether edge overhang is allowed at all
- whether some cases can be stacked directly on top of others
- whether a brick-wall pattern is required for stability
- whether columns are legal for specific SKUs or stack configurations
- whether layers are fixed or variable
- if the load must be “fully supported” by the pallet deck or if partial support is acceptable
- if the distribution of mass must be balanced across the pallet footprint
- if forklift or clamp handling restrictions change the layout rules
- whether the case pattern must be symmetric or visually legible for loading staff

## Operational goals

The real objective function should account for multiple goals:

1. maximize pallet volume utilization
2. minimize voids on each layer
3. minimize plan-view overhang and edge protrusion
4. minimize underhang or lost deck area
5. respect max height and load distribution
6. avoid unstable or unrealistic stack patterns
7. prefer consistent, repeatable loads for warehouse operations
8. keep algorithm runtime within decision-support needs

A common objective is a weighted sum such as:

Objective = w1 * wasted_area + w2 * overhang + w3 * underhang + w4 * instability + w5 * weight_balance + w6 * height_penalty

The weights depend on business priority. For example, a fragile, retail-facing load may heavily penalize instability, whereas a bulk logistics load may prioritize volume and throughput.

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

Two solvers can build a layer, and the solver keeps whichever layer holds more cases.

**Block packer.** A recursive guillotine search over the deck: each region is either filled with a uniform grid of one case orientation or cut in two, and each half is solved the same way. It finds the classic block patterns. For example, 5×8 cases on a 40×48 deck give the full 48, where the original greedy packer managed 45. When the search space is very large (tiny cases on a big deck), it is limited to two-block patterns so it stays responsive.

**GA layer search** (genetic algorithm). It starts from the **malleable bound**: how many cases would fit if they could be squeezed into any shape. For a whole pallet that's the space above the deck divided by the case volume. Because layers are flat and identical, this works out to `floor(deck area / case footprint)` per layer, which is the GA's target.
- **Encoding:** a chromosome has one gene per case up to the target, and each gene picks that case's orientation.
- **Decoding:** cases are placed in order at the bottom-left-most free spot, which can produce interlocking (non-guillotine) patterns that the block packer can't.
- **Objective:** `placed − penalty × unplaced`, so the bound itself is the optimum.
- **Search:** two-point crossover, point and block mutation, tournament selection and elitism. It stops early at the bound.
- **When it runs:** only when the block packer falls short of the bound, the footprint isn't square, and the target is at most 150 cases per layer.
- **Example:** for 9×7 cases on CHEP it finds 28 per layer, where the block packer finds 27 (the bound is 30). Defaults are 40 generations, population 24, seed 0, so results are reproducible.

### Layers and build height

- `Pallet.height` is the **max build height measured from the floor, including the pallet**. The space for cases is `height − deck_height`. For example, a 60" build on a 6" CHEP deck leaves 54".
- **Every layer has a flat top.** All cases in a layer share the same upright dimension, so the number of layers is `floor((max build height − deck height) / layer height)`. Every full layer uses the same pattern. A partial top layer, which happens when the weight limit or quantity runs out first, fills from case 1 outward.
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
- `solve_pallet_layout(pallet, cases, optimize=True, optimization_generations=40, optimization_population=24, optimization_seed=0, stacking="interlock", min_support=0.7)`: places the given cases and returns a `LayoutResult`. Pass `optimize=False` to use the block packer only.
- `maximize_case_count(pallet, case, optimize=True, ..., stacking="interlock", min_support=0.7)`: returns the largest count that fits, with its `LayoutResult`. It takes the same options.
- `optimize_layout(pallet, cases, generations=..., population_size=..., seed=...)`: shorthand for `solve_pallet_layout` with the GA on.
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

The app finds the most cases that fit and re-solves whenever an input changes. Every input that affects the solve is in the sidebar, with each label and value on one line:

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
  - The GA layer search switch, with its generations, population and seed.
  - Settings that don't apply are greyed out rather than hidden, so their values are kept.

The results area is split 50:50 between the 3D view and the results:

- **Headline**: the case count and layer breakdown, e.g. "96 cases fit · 6 layers × 16".
- **3D view**: an interactive Plotly model of the built pallet. Drag to spin (turntable rotation, so the pallet stays upright), scroll to zoom, and use the Iso, Front, Side and Top buttons to reset the viewpoint. The orbital-rotation and pan tools are removed. The deck is brown, layers alternate shades, and red dashes mark the max build height. Loads over 6,000 cases are drawn as one block per layer.
- **Metrics**: cases, malleable bound, layers, cube use, deck coverage, load weight, build height (deck + load), headroom, interlock and minimum support. A caption names the stacking and flip, e.g. "even layers rotated 180°".
- **Limit**: what stops the count going higher (pallet space, max weight, max volume or max plan area), or why a run is infeasible.
- **Solver status**:
  - A table of every solver run, with the total solve time: layer family, cases per layer, the bound, interlock, iterations, evaluations, time, whether it was used, and notes (for example why the GA was skipped).
  - When the GA runs, a chart of its best and mean objective per generation, plus best interlock on a second axis when stacking interlocks. The bound and the block packer's score are drawn as reference lines.
- **Tabs**:
  - **Placements**: the layer, pattern (A or flipped B), x/y/z and size for each case. Columns fit their content.
  - **Sensitivity**: re-solves every combination of case-size changes. Each of length, width and height is either left unchanged or moved by one of its own steps, independently of the others.
    - **Settings table:** each dimension has its own on/off, change type (a fixed amount, default 0.2 in / 0.5 cm, or a percentage, default 2%), step size, and 1–3 steps each way (default 1).
    - **Runs:** (2n+1)³ − 1 for n steps on all three dimensions: 26 at 1 step, up to 342 at 3. A progress bar shows the run. Steps that would take a dimension to zero or below are skipped and listed.
    - **Results:** for each combination, the change to each dimension ("–" when unchanged), the case size, cases and the change from the base, Ti (cases per layer) and Hi (layers), deck coverage, cube use and interlock. Case counts and percentage columns are drawn as in-cell bars.
    - **Order:** the base case is highlighted at the top, and the combinations follow, ranked by fitness: most cases, then cube use, interlock and deck coverage.
  - **Export**:
    - **Excel**: Summary, Placements, Solver runs, GA history and Sensitivity sheets.
    - **CSV**: the placement grid.
    - **JSON**: everything, including the inputs.

## Recommendations for future versions

- **More interlock options**: patterns that alternate between two different layouts (not just flips), and user-set interlock targets.
- **Exact layer bounds**: the GA narrows the gap to the malleable bound but can't prove optimality. An exact 2D solver (for example CP-SAT) could certify the best layer for awkward case sizes.
- **Stability checks**: center-of-gravity and load-distribution checks, and a per-case crush or max-stack-weight limit.
- **Weighted objective**: tunable coefficients to trade density against stability, beyond the current count-first ranking.
- **Mixed loads**: support for more than one case type per pallet.
- **Export**: printable loading instructions (a layer sheet) alongside the JSON.

## Summary

This is a real-world rectangular packing problem with strong operational constraints. The project deliberately handles one case type per pallet run, which keeps the model easy to reason about, validate and present. Within that scope, it packs each layer with block patterns, improves on them with a GA that targets the malleable bound, stacks flat layers to the max build height (interlocked by flipping alternate layers where that helps), respects weight, volume and area limits, explains what limits each result and which solver produced it, shows the built pallet in an interactive 3D view, and runs a case-size sensitivity analysis.
