"""Streamlit app tests (headless, via streamlit.testing.v1.AppTest)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import streamlit
from streamlit.testing.v1 import AppTest

from pallet_builder import inputs
from ui.style import STREAMLIT_TEST_IDS

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
PROBE = str(Path(__file__).resolve().parent / "app_state_probe.py")
SAMPLES = {doc["name"]: doc for doc in (inputs.load(p) for p in inputs.sample_paths(ROOT / "samples"))}


def run(script: str = APP) -> AppTest:
    at = AppTest.from_file(script, default_timeout=600).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def metric(at: AppTest, label: str) -> str:
    return next(m.value for m in at.metric if m.label == label)


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def sensitivity_table(at: AppTest):
    return next((d.value for d in at.dataframe if "Case size" in d.value.columns), None)


def test_default_page_opens_on_overview():
    at = run()
    assert [t.label for t in at.tabs][:7] == ["Overview", "Input", "Summary", "3D view", "Placements",
                                              "By iteration", "Sensitivity"]
    assert at.session_state["main_tab"] == "Overview"
    assert metric(at, "Cases") == "96" and metric(at, "Layers") == "6 layers × 16"


def test_input_tab_result_shows_every_metric():
    at = run()
    labels = [m.label for m in at.metric]
    every = ["Cases", "Layers", "Max by volume", "Cube use", "Deck coverage", "Load weight", "Build height",
             "Headroom", "Interlock", "Min support"]
    assert labels[:10] == every  # the Input tab's Result section (drawn before Summary) has the full grid
    assert labels.count("Cases") == 2  # and Summary shows the same metrics
    assert any("Limited by pallet space" in i.value for i in at.info)


@pytest.mark.parametrize("name", list(SAMPLES))
def test_every_sample_loads_and_matches_its_expected_result(name):
    at = run()
    at.selectbox(key="sample_choice").set_value(name).run()
    button(at, "Load sample").click().run()
    assert not at.exception
    assert metric(at, "Cases") == str(SAMPLES[name]["expected"]["cases"])


@pytest.mark.parametrize("name", list(SAMPLES))
def test_loading_then_saving_a_sample_keeps_every_input(name):
    at = run(PROBE)
    at.selectbox(key="sample_choice").set_value(name).run()
    button(at, "Load sample").click().run()
    saved = inputs.loads(at.session_state["_probe_document"])
    for section in ("units", "pallet", "build", "case", "solve", "sensitivity", "name", "description"):
        assert saved[section] == SAMPLES[name][section], section


def test_unit_switch_round_trip_restores_values():
    at = run()
    at.number_input(key="c_weight").set_value(40.0).run()
    at.selectbox(key="units").set_value("Metric (cm, kg)").run()
    assert at.session_state["p_len"] == pytest.approx(101.6)
    at.selectbox(key="units").set_value("US (in, lb)").run()
    assert (at.session_state["p_len"], at.session_state["c_weight"]) == (40.0, 40.0)


def test_disabled_settings_keep_their_values():
    at = run()
    at.selectbox(key="stacking").set_value("column").run()
    at.selectbox(key="stacking").set_value("no_column").run()
    assert at.session_state["min_support"] == 70.0
    at.toggle(key="ga_on").set_value(False).run()
    at.toggle(key="ga_on").set_value(True).run()
    assert (at.session_state["ga_gens"], at.session_state["ga_pop"]) == (40, 24)


def test_auto_solve_off_waits_for_the_solve_button():
    at = run()
    at.toggle(key="auto_solve").set_value(False).run()
    at.number_input(key="c_wid").set_value(10.5).run()
    assert metric(at, "Cases") == "96" and any("press **Solve**" in w.value for w in at.warning)
    button(at, "Solve").click().run()
    assert metric(at, "Cases") != "96" and not any("press **Solve**" in w.value for w in at.warning)


def test_sensitivity_only_computes_while_its_tab_is_open():
    at = run()
    assert sensitivity_table(at) is None  # Summary is open: no sensitivity solves
    at.session_state["main_tab"] = "Sensitivity"
    at.run()
    table = sensitivity_table(at)
    assert table is not None and len(table) == 27 and table.iloc[0]["Case size"] == "12 × 10 × 8"
    assert at.session_state["sens_on"] is True


def test_reset_to_defaults_restores_the_default_inputs():
    at = run()
    at.number_input(key="c_len").set_value(9.0).run()
    button(at, "Reset to defaults").click().run()
    assert at.session_state["c_len"] == 12.0 and metric(at, "Cases") == "96"


def test_invalid_input_shows_an_error_instead_of_crashing():
    at = run()
    at.number_input(key="p_height").set_value(3.0).run()
    assert not at.exception
    assert any("max build height must be greater than the deck height" in e.value for e in at.error)


def test_summary_explains_cached_results_and_solver_limits():
    at = run()
    at.run()  # same inputs again: served from the cache
    assert any("cached (first solve took" in m.value for m in at.markdown if "Solver status" in m.value)
    at.toggle(key="c_tsu").set_value(False).run()
    assert any("same upright side" in m.value for m in at.markdown)


def test_css_targets_streamlit_elements_that_still_exist():
    """The compact Input layout styles Streamlit's internal test IDs; fail loudly if an upgrade renames one."""
    static = Path(streamlit.__file__).parent / "static"
    bundle = "".join(path.read_text(encoding="utf-8", errors="ignore") for path in static.rglob("*.js"))
    missing = [test_id for test_id in STREAMLIT_TEST_IDS if not re.search(re.escape(test_id), bundle)]
    assert not missing, f"Streamlit no longer renders: {missing}; update ui/style.py"


def test_overview_describes_every_tab():
    at = run()
    tabs = [t.label for t in at.tabs][:7]  # the page's main tab row
    overview = next(m.value for m in at.markdown if "### The tabs" in m.value)
    missing = [tab for tab in tabs if f"| **{tab}** |" not in overview]
    assert not missing, f"Overview's tab table is missing: {missing}"


def test_result_sits_at_the_bottom_of_the_input_tab():
    at = run()
    markdown = [m.value for m in at.markdown]
    result_label = next(i for i, v in enumerate(markdown) if "section-label'>Result" in v)
    last_input_section = max(i for i, v in enumerate(markdown) if "section-label'>Solve" in v)
    assert result_label > last_input_section


def test_result_tabs_start_with_what_was_solved():
    at = run()
    summary = next(m.value for m in at.markdown if "class='input-summary'" in m.value)
    for part in ("<b>Pallet</b> CHEP 40 \u00d7 48 in", "<b>Build</b> max height 60 in",
                 "<b>Case</b> 12 \u00d7 10 \u00d7 8 in, 20 lb", "<b>Solve</b> interlock when possible"):
        assert part in summary
    at.toggle(key="auto_solve").set_value(False).run()
    at.number_input(key="c_len").set_value(11.0).run()
    stale = next(m.value for m in at.markdown if "class='input-summary'" in m.value)
    assert "12 \u00d7 10 \u00d7 8 in" in stale and "inputs have changed" in stale  # describes the solved inputs
