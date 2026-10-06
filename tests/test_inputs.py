from pathlib import Path

import pytest

from pallet_builder import Case, Pallet, maximize_case_count
from pallet_builder.inputs import (
    FILE_EXTENSION,
    InputFileError,
    default_document,
    dumps,
    loads,
    sample_paths,
    solver_arguments,
)

SAMPLES = sample_paths(Path(__file__).resolve().parents[1] / "samples")


def test_samples_exist_with_our_extension():
    assert len(SAMPLES) >= 10
    assert all(path.suffix == FILE_EXTENSION for path in SAMPLES)


@pytest.mark.parametrize("path", SAMPLES, ids=[path.stem for path in SAMPLES])
def test_every_sample_solves_to_its_expected_result(path):
    doc = loads(path.read_text(encoding="utf-8"))
    pallet_kwargs, case_kwargs, options = solver_arguments(doc)
    count, result = maximize_case_count(Pallet(**pallet_kwargs), Case(**case_kwargs), **options)

    expected = doc["expected"]
    assert (count, result.layers, result.cases_per_layer) == (
        expected["cases"], expected["layers"], expected["cases_per_layer"])


def test_save_and_load_round_trip_keeps_every_value():
    doc = default_document()
    doc["units"] = "Metric"
    doc["pallet"].update(preset="Custom", length=110.0, width=95.5, deck_height=15.0, max_weight=None)
    doc["build"].update(max_height=170.0, max_volume=0.0)  # 0 is a real limit, None is no limit
    doc["case"].update(length=31.25, this_side_up=False)
    doc["solve"].update(stacking="no_column", min_support_pct=80.0)
    doc["solve"]["ga"].update(stop_rule="no_improvement", stall=30, generations=600, population=64, seed=7)
    doc["sensitivity"]["dimensions"]["width"].update(enabled=False, by="percent", percent_step=3.5, steps=3)

    assert loads(dumps(doc)) == loads(dumps(loads(dumps(doc))))
    reloaded = loads(dumps(doc))
    assert reloaded["build"]["max_volume"] == 0.0 and reloaded["pallet"]["max_weight"] is None
    assert reloaded["solve"]["ga"]["stall"] == 30
    assert reloaded["sensitivity"]["dimensions"]["width"]["percent_step"] == 3.5


def test_partial_file_fills_in_defaults():
    doc = loads('{"format": "pallet-builder-input", "case": {"length": 9, "width": 7}}')
    assert doc["case"]["length"] == 9 and doc["case"]["height"] == 8.0
    assert doc["pallet"]["preset"] == "CHEP"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not json", "Not valid JSON"),
        ("[1, 2]", "must contain a JSON object"),
        ('{"format": "something-else"}', "Not a Pallet Builder input file"),
        ('{"format": "pallet-builder-input", "version": 99}', "Unsupported file version"),
        ('{"format": "pallet-builder-input", "case": {"length": -1}}', "case.length must be at least"),
        ('{"format": "pallet-builder-input", "case": {"this_side_up": "yes"}}', "case.this_side_up must be true or false"),
        ('{"format": "pallet-builder-input", "solve": {"stacking": "pyramid"}}', "solve.stacking must be one of"),
        ('{"format": "pallet-builder-input", "build": {"max_height": 5}}', "build.max_height must be greater"),
    ],
)
def test_invalid_files_are_rejected_with_a_clear_reason(text, message):
    with pytest.raises(InputFileError, match=message):
        loads(text)
