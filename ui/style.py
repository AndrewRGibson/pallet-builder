"""Page CSS. The compact Input tab layout targets Streamlit's internal element test IDs, which can change
between Streamlit releases; ``STREAMLIT_TEST_IDS`` lists them so a test can check they still exist in
the installed Streamlit (see tests/test_app.py), and pyproject.toml pins the Streamlit minor version.
"""

from __future__ import annotations

import streamlit as st

# Streamlit element test IDs the CSS below depends on.
STREAMLIT_TEST_IDS = (
    "stVerticalBlock",
    "stNumberInput",
    "stNumberInputContainer",
    "stNumberInputStepUp",
    "stNumberInputStepDown",
    "stSelectbox",
    "stWidgetLabel",
    "stMetricValue",
)

CSS = """
<style>
    .block-container { padding-top: 2.75rem; padding-bottom: 0.5rem; }
    /* Input tab: compact rows with label and value on one line. */
    .st-key-inputs [data-testid="stVerticalBlock"] { gap: 0.2rem; }
    .st-key-inputs hr { margin: 1.1rem 0 0.6rem; }
    /* Compact value boxes: 28px number and select boxes (Streamlit's default is 40px). */
    .st-key-inputs [data-testid="stNumberInputContainer"],
    .st-key-inputs [data-testid="stSelectbox"] > div:last-child > div {
        height: 28px !important; min-height: 0 !important;
    }
    .st-key-inputs [data-testid="stNumberInput"] input,
    .st-key-inputs [data-testid="stSelectbox"] input {
        height: 26px !important; min-height: 0 !important; padding-top: 2px !important; padding-bottom: 2px !important;
    }
    .st-key-inputs [data-testid="stSelectbox"] button {
        height: 26px !important; padding-top: 0 !important; padding-bottom: 0 !important;
    }
    .st-key-inputs [data-testid="stNumberInput"],
    .st-key-inputs [data-testid="stSelectbox"] {
        display: flex; flex-direction: row; align-items: center; gap: 0.5rem;
    }
    .st-key-inputs [data-testid="stNumberInput"] > [data-testid="stWidgetLabel"],
    .st-key-inputs [data-testid="stSelectbox"] > [data-testid="stWidgetLabel"] {
        flex: 0 0 40%; min-height: 0; margin: 0; padding: 0;
    }
    .st-key-inputs [data-testid="stNumberInput"] > div,
    .st-key-inputs [data-testid="stSelectbox"] > div {
        flex: 1 1 0; min-width: 0;
    }
    /* The +/- steppers crowd a half-width field; arrow keys still step the value. */
    .st-key-inputs [data-testid="stNumberInputStepUp"],
    .st-key-inputs [data-testid="stNumberInputStepDown"] { display: none; }
    .section-label { font-size: 0.75rem; font-weight: 700; letter-spacing: 0.06em;
                     text-transform: uppercase; opacity: 0.65; margin: 0.2rem 0 0.25rem; }
    [data-testid="stMetricValue"] { font-size: 1.35rem; }
    /* Result strip at the top of the Input tab. */
    .result-strip { padding: 0.45rem 0.8rem; border-radius: 0.5rem; background: rgba(59, 130, 246, 0.08);
                    border: 1px solid rgba(59, 130, 246, 0.25); margin-bottom: 0.4rem; }
</style>
"""


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
