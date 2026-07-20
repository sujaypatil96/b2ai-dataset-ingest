"""Encoding-agnostic ordinal resolution and string-valued choices.

Covers the drift the synthetic tree hid: items on a non-default scale (``tough_to_work``),
string-coded choices (VHI-10 style), numeric-coded cells ("3.0"), and the PHI-safe warning
that never echoes the raw answer.
"""

import logging

from b2ai_dataset_ingest.mapping.engine import MappingEngine
from b2ai_dataset_ingest.reporting import IngestReport

GAD7_TOUGH_TO_WORK = {
    "tough_to_work": {
        "choices": [
            {"name": {"en": "Not difficult at all"}, "value": 0},
            {"name": {"en": "Somewhat difficult"}, "value": 1},
            {"name": {"en": "Very difficult"}, "value": 2},
            {"name": {"en": "Extremely difficult"}, "value": 3},
        ]
    }
}


def _engine(items):
    return MappingEngine({"table": "gad7_anxiety", "items": items})


def test_off_scale_item_resolves_from_flat_dict_choices():
    # tough_to_work is on the difficulty scale, absent from any 4-point frequency
    # ordinal_scale fallback -> only the data-dict choices can resolve it.
    engine = _engine({"tough_to_work": {"id": "LOINC:69722-7", "label": "difficulty"}})
    [m] = engine.measurements({"tough_to_work": "Very difficult"}, GAD7_TOUGH_TO_WORK)
    assert m.value_quantity.value == 2.0


def test_string_valued_choices_resolve_positionally():
    # VHI-10-style: choice `value` is a string code; the ordinal is the positional index.
    data_dict = {
        "strain_voice": {
            "choices": [
                {"name": {"en": "Never"}, "value": "never"},
                {"name": {"en": "Almost Never"}, "value": "almostNever"},
                {"name": {"en": "Sometimes"}, "value": "sometimes"},
            ]
        }
    }
    engine = _engine({"strain_voice": {"id": "b2ai:x", "label": "strain"}})
    [m] = engine.measurements({"strain_voice": "Sometimes"}, data_dict)
    assert m.value_quantity.value == 2.0  # positional index of "Sometimes"


def test_numeric_coded_cell_resolves_against_named_choices():
    # If real cells ship coded ("2" or "2.0") instead of the label, still resolve.
    engine = _engine({"tough_to_work": {"id": "LOINC:69722-7", "label": "difficulty"}})
    [m2] = engine.measurements({"tough_to_work": "2"}, GAD7_TOUGH_TO_WORK)
    assert m2.value_quantity.value == 2.0
    [m3] = engine.measurements({"tough_to_work": "3.0"}, GAD7_TOUGH_TO_WORK)
    assert m3.value_quantity.value == 3.0


def test_boolean_choice_values_are_not_treated_as_ordinals():
    # isinstance(True, int) is True in Python; a bool value must fall back to positional.
    data_dict = {
        "yesno": {
            "choices": [
                {"name": {"en": "No"}, "value": False},
                {"name": {"en": "Yes"}, "value": True},
            ]
        }
    }
    engine = _engine({"yesno": {"id": "b2ai:yn", "label": "yn"}})
    [m] = engine.measurements({"yesno": "Yes"}, data_dict)
    assert m.value_quantity.value == 1.0  # positional, not int(True)==1 by coincidence-only


def test_unresolved_answer_is_skipped_and_counted_without_leaking_value(caplog):
    engine = _engine({"nervous_anxious": {"id": "LOINC:69725-0", "label": "nervous"}})
    report = IngestReport()
    with caplog.at_level(logging.WARNING):
        out = engine.measurements(
            {"nervous_anxious": "SECRET-PII-ANSWER"}, data_dict={}, report=report
        )
    assert out == []  # nothing resolved -> item skipped
    assert report.items_unresolved["gad7_anxiety.nervous_anxious"] == 1
    # PHI-safe: the raw answer must never appear in logs.
    assert "SECRET-PII-ANSWER" not in caplog.text
    assert "nervous_anxious" in caplog.text  # the column name is fine to log


def test_ordinal_scale_fallback_still_works_without_data_dict():
    engine = MappingEngine(
        {
            "table": "phq9",
            "ordinal_scale": {"Not at all": 0, "Several days": 1},
            "items": {"feeling_depressed": {"id": "LOINC:44255-8", "label": "d"}},
        }
    )
    [m] = engine.measurements({"feeling_depressed": "Several days"})
    assert m.value_quantity.value == 1.0
