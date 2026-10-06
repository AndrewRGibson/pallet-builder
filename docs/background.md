# Background: pallet loading as an optimization problem

Design notes written before the app was built: how the problem is framed, the operations-research methods that apply, and the constraints and goals a full solution should consider. For what Pallet Builder actually does today, see the [README](../README.md).

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
