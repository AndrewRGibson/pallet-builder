# Pallet Builder

This project is a practical starting point for a pallet-loading optimizer. For this phase, each run is intentionally scoped to stacking a single case type on a pallet: one SKU, one fixed case dimension set, repeated as many times as needed to fill the pallet.

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

This repo implements the first step in that roadmap: a deterministic heuristic layered packer for a fixed pallet footprint and a single repeated case type. That gives a quick, explainable baseline for one-case pallet runs and keeps the project tightly aligned with the current scope.

## Current solver behavior

The package exposes:

- Case: a case definition with dimensions and optional weight
- Pallet: pallet envelope and constraints
- solve_pallet_layout: a heuristic placement function that returns feasibility, utilization, and placement data for a single case type

A simple usage example is:

```python
from pallet_builder import Case, Pallet, solve_pallet_layout

pallet = Pallet(length=10, width=8, height=6, max_weight=2000)
cases = [
    Case("A", 4, 2, 2, weight=100),
    Case("B", 4, 2, 2, weight=110),
    Case("C", 3, 2, 2, weight=120),
]

result = solve_pallet_layout(pallet, cases)
print(result.feasible)
print(result.utilization)
print(result.placements)
```

## Recommendations for future versions

The next version should likely add:

- exact 2D/3D packing with candidate placement generation for single-case runs
- support for more pallet profiles and unit conversions
- legal stacking and column rules
- center-of-gravity and load distribution checks
- a weighted objective function with tunable coefficients
- a GA or local-search improvement stage for difficult layouts
- a richer API that outputs a pallet map, layer list, and explicit reasons for infeasibility

## UI roadmap

The next major step is a simple user interface for this single-case workflow. The UI should allow a user to:

- select a pallet type or enter custom pallet dimensions
- enter one case type: length, width, height, weight, and quantity
- choose units (in, mm, cm, etc.)
- review a live pallet plan with x/y placement coordinates
- see utilization, overhang, underhang, and feasibility indicators
- export or save the computed layout for later review

The interface should stay intentionally narrow: one pallet, one case type, one optimization run at a time. This keeps the UX straightforward while the solver remains focused on the core problem.

## Streamlit UI

The project now includes a simple Streamlit front-end for the single-case pallet workflow.

Run it with:

```bash
uv run streamlit run app.py
```

The app re-solves as inputs change. The sidebar holds every input that affects the solve:

- **Pallet**: preset (CHEP, GMA, EUR 1200×800, EUR 1000×1200) or custom dimensions, length and weight units, max load height, max weight, plus max volume, max plan area and deck height under "More limits". Setting a limit to 0 means no limit.
- **Case**: length, width, height, weight and unit, plus *This side up*. Turning *This side up* off lets the solver tip cases.
- **Solve**: *Max cases* finds the largest count that fits. *Fixed quantity* places a given number of cases and can turn on the GA optimizer (generations, population, seed).

The results page shows the plan view next to the status, case count, deck coverage, load weight and height, and what limits the count. Tabs below give the placement table and a JSON export of the inputs and layout.

## Summary

This is a real-world rectangular packing problem with strong operational constraints. A good single-case solution will combine a constructive heuristic with a more rigorous optimization layer. For this project, the initial implementation is intentionally limited to one case type per pallet run, which keeps the model easier to reason about, easier to validate, and easier to present in a UI.

The next phase is a front-end that lets a user enter a pallet and one case type, then immediately see a loading plan, utilization, and feasibility results.
