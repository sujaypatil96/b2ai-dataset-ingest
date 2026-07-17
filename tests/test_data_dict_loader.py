"""Data-dict envelope normalization: the real (flat) and synthetic (nested) shapes.

These lock in the fix for the highest-blast-radius drift: the real b2aiprep release ships
*flat* dicts (top-level keys are column names), while the local synthetic generator wraps
them under ``{table: {data_elements: {...}}}``. The reader must understand both.
"""

import json

from b2ai_dataset_ingest.mapping.loaders import load_data_dict, normalize_data_dict

FLAT_REAL = {
    "participant_id": {"description": "id", "valueType": ["xsd:string"]},
    "nervous_anxious": {
        "description": "nervous",
        "datatype": ["xsd:integer"],
        "valueType": ["xsd:integer"],
        "choices": [{"name": {"en": "Not at all"}, "value": 0}],
    },
}

NESTED_SYNTHETIC = {
    "gad7_anxiety": {
        "description": "synthetic",
        "url": "https://example/schema",
        "data_elements": {
            "participant_id": {"description": "id", "valueType": "xsd:string"},
            "nervous_anxious": {
                "description": "nervous",
                "datatype": ["xsd:integer"],
                "choices": [{"name": {"en": "Not at all"}, "value": 0}],
            },
        },
    }
}


def test_normalize_flat_real_dict_returned_as_is():
    out = normalize_data_dict(FLAT_REAL)
    assert set(out) == {"participant_id", "nervous_anxious"}
    assert out["nervous_anxious"]["choices"][0]["value"] == 0


def test_normalize_nested_synthetic_unwraps_data_elements():
    out = normalize_data_dict(NESTED_SYNTHETIC)
    # The table envelope and its metadata keys are stripped; columns are top-level.
    assert set(out) == {"participant_id", "nervous_anxious"}
    assert "data_elements" not in out
    assert "url" not in out


def test_normalize_empty_and_garbage_are_safe():
    assert normalize_data_dict({}) == {}
    assert normalize_data_dict(None) == {}
    assert normalize_data_dict([1, 2, 3]) == {}


def test_normalize_unrecognized_envelope_warns_and_returns_empty(caplog):
    # A dict whose values are not element-shaped and carry no data_elements.
    weird = {"a": 1, "b": "two"}
    assert normalize_data_dict(weird, source="weird.json") == {}
    assert any("unrecognized data-dict envelope" in r.message for r in caplog.records)


def test_load_data_dict_reads_both_shapes(tmp_path):
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps(FLAT_REAL))
    nested = tmp_path / "nested.json"
    nested.write_text(json.dumps(NESTED_SYNTHETIC))
    assert set(load_data_dict(flat)) == {"participant_id", "nervous_anxious"}
    assert set(load_data_dict(nested)) == {"participant_id", "nervous_anxious"}


def test_load_data_dict_missing_file_is_empty(tmp_path):
    assert load_data_dict(tmp_path / "nope.json") == {}
