from __future__ import annotations

import math

import matplotlib.pyplot as plt
import streamlit as st

from pallet_builder import Case, Pallet, STANDARD_PALLETS, maximize_case_count


st.set_page_config(page_title="Pallet Builder", page_icon="📦", layout="wide")


UNIT_OPTIONS = ["in", "mm", "cm", "m", "ft", "yd"]


def _standard_pallets() -> list[str]:
    return ["Custom", *sorted(STANDARD_PALLETS)]


def _build_case_list(case_length: float, case_width: float, case_height: float, case_weight: float, case_unit: str, quantity: int) -> list[Case]:
    return [
        Case(
            name=f"Case {idx + 1}",
            length=case_length,
            width=case_width,
            height=case_height,
            weight=case_weight,
            unit=case_unit,
        )
        for idx in range(quantity)
    ]


def _solve_max_count(pallet: Pallet, case: Case):
    progress_bar = st.progress(0.0, text="Searching for maximum feasible case count...")
    iteration_text = st.empty()

    def _progress_callback(iteration: int, lower: int, upper: int, tested_count: int, result):
        if upper == 0:
            progress_bar.progress(1.0, text="No cases fit on the pallet.")
            iteration_text.write(f"Iteration {iteration}: no feasible count found above 0.")
            return
        percent = (iteration / max(1, (lower + upper + 2)))
        progress_bar.progress(min(percent, 1.0), text=f"Testing counts around {tested_count}...")
        iteration_text.write(f"Iteration {iteration}: testing count {tested_count} using bounds [{lower}, {upper}].")

    max_count, result = maximize_case_count(pallet, case, progress_callback=_progress_callback)
    progress_bar.progress(1.0, text=f"Solved: {max_count} cases fit.")
    iteration_text.write(f"Final result: {max_count} cases fit on the pallet.")
    return max_count, result


def _render_layout(pallet: Pallet, result) -> None:
    if not result.placements:
        st.info("No layout to draw yet.")
        return

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.set_facecolor("#f8fafc")

    pad = max(1.0, max(pallet.length, pallet.width) * 0.12)
    ax.set_xlim(-pad, pallet.length + pad)
    ax.set_ylim(-pad, pallet.width + pad)
    ax.set_aspect("equal")
    ax.set_xlabel(f"Length ({pallet.unit})")
    ax.set_ylabel(f"Width ({pallet.unit})")
    ax.set_title("Pallet footprint plan view")

    ax.add_patch(plt.Rectangle((0, 0), pallet.length, pallet.width, fill=False, edgecolor="black", linewidth=2))

    for placement in result.placements:
        rect = plt.Rectangle(
            (placement.x, placement.y),
            placement.length,
            placement.width,
            facecolor="#93c5fd",
            edgecolor="#1d4ed8",
            linewidth=1.5,
            alpha=0.75,
        )
        ax.add_patch(rect)
        cx = placement.x + placement.length / 2
        cy = placement.y + placement.width / 2
        ax.text(cx, cy, placement.case_name.split()[0], ha="center", va="center", fontsize=8)

    ax.grid(True, linestyle="--", alpha=0.35)
    st.pyplot(fig)


st.title("Pallet Builder")
st.caption("Single case type pallet planner")

left, right = st.columns([1, 2])

with left:
    with st.form("pallet_form"):
        pallet_mode = st.selectbox("Pallet source", _standard_pallets(), index=1 if "CHEP" in _standard_pallets() else 0)

        if pallet_mode == "Custom":
            pallet_length = st.number_input("Pallet length", min_value=1.0, value=40.0, step=None)
            pallet_width = st.number_input("Pallet width", min_value=1.0, value=48.0, step=None)
            pallet_height = st.number_input("Pallet height", min_value=0.1, value=6.0, step=None)
            pallet_unit = st.selectbox("Pallet unit", UNIT_OPTIONS, index=0)
            max_weight = st.number_input("Max pallet weight", min_value=0.0, value=2200.0, step=None)
            pallet = Pallet(
                length=pallet_length,
                width=pallet_width,
                height=pallet_height,
                unit=pallet_unit,
                max_weight=max_weight,
            )
        else:
            spec = STANDARD_PALLETS[pallet_mode]
            pallet_unit = st.selectbox("Pallet unit", UNIT_OPTIONS, index=UNIT_OPTIONS.index(spec["unit"]))
            pallet = Pallet.from_standard(pallet_mode, unit=pallet_unit)
            st.write(f"Preset: {pallet_mode}")
            st.write(f"{pallet.length} {pallet.unit} x {pallet.width} {pallet.unit}")

        st.markdown("---")
        case_length = st.number_input("Case length", min_value=0.1, value=8.0, step=None)
        case_width = st.number_input("Case width", min_value=0.1, value=8.0, step=None)
        case_height = st.number_input("Case height", min_value=0.1, value=2.0, step=None)
        case_weight = st.number_input("Case weight", min_value=0.0, value=10.0, step=None)
        case_unit = st.selectbox("Case unit", UNIT_OPTIONS, index=0)

        submitted = st.form_submit_button("Generate layout")

if not submitted:
    st.info("Set the pallet and case values, then click Generate layout.")
    st.stop()

case = Case(
    name="Case",
    length=case_length,
    width=case_width,
    height=case_height,
    weight=case_weight,
    unit=case_unit,
)
max_count, result = _solve_max_count(pallet, case)

with right:
    st.subheader("Results")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Feasible", "Yes" if result.feasible else "No")
    col2.metric("Utilization", f"{result.utilization:.2%}")
    col3.metric("Placed", str(max_count))
    col4.metric("Weight", f"{result.total_weight:.1f} {pallet.unit}")

    if result.violations:
        st.warning("\n".join(result.violations))

    if result.feasible:
        st.success("A feasible pallet layout was found.")
    else:
        st.error("This run is not feasible under the current constraints.")

    _render_layout(pallet, result)

    if result.placements:
        placement_rows = [
            {
                "case": placement.case_name,
                "x": round(placement.x, 2),
                "y": round(placement.y, 2),
                "length": round(placement.length, 2),
                "width": round(placement.width, 2),
                "height": round(placement.height, 2),
                "orientation": placement.orientation,
            }
            for placement in result.placements
        ]
        st.dataframe(placement_rows, use_container_width=True)
