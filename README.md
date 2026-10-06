# Pallet Builder

This project is a practical starting point for a pallet-loading optimizer. For this phase, each run is intentionally scoped to stacking a single case type on a pallet: one SKU, one fixed case dimension set, repeated as many times as needed to fill the pallet.

## Quick start

```bash
uv sync                          # install dependencies
uv run streamlit run app.py      # open the planner UI (3D view, layer plan, export)
uv run pytest                    # run the test suite
```

The solver packs each layer with exact block patterns and stacks flat layers up to the max build height, including the pallet deck. See [Current solver behavior](#current-solver-behavior) and [Streamlit UI](#streamlit-ui) for details.

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

This repo implements steps 1–3 for a single repeated case type: an exact-geometry block packer for each layer, and flat layers stacked up to the max build height within the weight and other load limits. Steps 4 and 5 (interlocking or column rules, stability checks, and metaheuristic improvement) are still open.

## Current solver behavior

### Layer pattern

Each layer is built by a **block packer**. This is a recursive guillotine search over the deck: each region is either filled with a uniform grid of one case orientation or cut in two, and each half is solved the same way. It finds the classic block patterns. For example, 5×8 cases on a 40×48 deck give the full 48, where the original greedy packer managed 45. When the search space is very large (tiny cases on a big deck), it is limited to two-block patterns so it stays responsive.

### Layers and build height

- `Pallet.height` is the **max build height measured from the floor, including the pallet**. The space for cases is `height − deck_height`. For example, a 60" build on a 6" CHEP deck leaves 54".
- **Every layer has a flat top.** All cases in a layer share the same upright dimension, so the number of layers is `floor((max build height − deck height) / layer height)`. Every full layer uses the same pattern. A partial top layer, which happens when the weight limit or quantity runs out first, fills from case 1 outward.
- Cases marked *this side up* (the default) only rotate flat on the deck. With `this_side_up=False`, the solver tries each dimension as the upright one and keeps the option that stacks the most cases in total. Ties go to more cases per layer, for a wider base.
- With `height=None`, there is no build limit and the solver builds a single layer.

### Limits

`max_weight` caps the total case weight, `max_volume` caps the total case volume, and `max_plan_area` caps the combined case footprint. `maximize_case_count` takes the smaller of layers × cases per layer and those caps. A run that breaks a limit is reported as infeasible, with a reason for each limit it breaks.

### API

- `Case`: dimensions, weight, quantity, unit, and `this_side_up`.
- `Pallet`: deck length and width, `height` (max build height including the deck), `deck_height`, unit, and optional `max_weight`, `max_volume` and `max_plan_area`. `Pallet.from_standard(name, unit=..., max_build_height=...)` loads the CHEP, GMA, EUR_1200X800 and EUR_1000X1200 presets, and "EURO" is an alias for EUR_1200X800. Preset max weights are in lb for CHEP/GMA and kg for EUR. `Pallet` doesn't store a weight unit, so case weights must use the same unit.
- `solve_pallet_layout(pallet, cases)`: places the given cases and returns a `LayoutResult`.
- `maximize_case_count(pallet, case)`: returns the largest count that fits, with its `LayoutResult`.
- `LayoutResult` contains:
  - `placements`: x, y, z, size and orientation for each case, with z measured from the top of the deck.
  - `feasible` and `violations`.
  - `layers`, `cases_per_layer` and `max_layers`. Capacity is `max_layers × cases_per_layer`.
  - `utilization`: deck coverage of the base layer.
  - `volume_utilization`: case volume as a share of the space above the deck.
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

The app re-solves whenever an input changes. Every input that affects the solve is in the sidebar:

- **Pallet**:
  - Preset (CHEP, GMA, EUR 1200×800, EUR 1000×1200) or custom dimensions.
  - Length and weight units. Changing a unit converts the values already entered.
  - Max build height (including the pallet), deck height and max weight.
  - Max volume and max plan area, under "More limits".
  - Choosing a preset fills in typical values (60" or 1800 mm build height). Editing a pallet dimension switches the preset to "Custom". A limit of 0 means no limit.
- **Case**: length, width, height, weight and unit, plus *This side up*.
- **Solve**:
  - *Max cases* stacks as many full, flat layers as fit within the limits.
  - *Fixed quantity* places a given number of cases and reports any that don't fit.

The results area shows:

- **Headline**: the case count and layer breakdown, e.g. "96 cases fit · 6 layers × 16".
- **3D view**: an interactive Plotly model of the built pallet. Drag to spin, scroll to zoom, right-drag to pan, and use the Iso, Front, Side and Top buttons to reset the viewpoint. The deck is brown, layers alternate shades, and red dashes mark the max build height. Loads over 6,000 cases are drawn as one block per layer.
- **Layer plan**: a 2D view of the layer pattern. Rotated cases are highlighted.
- **Metrics**: status, cases, layers, cube use, deck coverage, load weight, build height (deck + load) and headroom.
- **Limit**: what stops the count going higher (pallet space, max weight, max volume or max plan area), or why a run is infeasible.
- **Tabs**: a placement table (layer and x/y/z for each case) and a JSON export of every input and the full layout.

## Recommendations for future versions

- **Interlocking layers**: alternate the pattern between layers (column vs. interlocked stacking) for load stability.
- **Better patterns**: non-guillotine layer patterns (for example pinwheels) for awkward case sizes, where the block packer can fall short of the area bound.
- **Stability checks**: center-of-gravity and load-distribution checks, and a per-case crush or max-stack-weight limit.
- **Weighted objective**: tunable coefficients to trade density against stability.
- **Mixed loads**: support for more than one case type per pallet.
- **Export**: printable loading instructions (a layer sheet) alongside the JSON.

## Summary

This is a real-world rectangular packing problem with strong operational constraints. The project deliberately handles one case type per pallet run, which keeps the model easy to reason about, validate and present. Within that scope, it packs each layer exactly with block patterns, stacks flat layers to the max build height, respects weight, volume and area limits, explains what limits each result, and shows the built pallet in an interactive 3D view.
