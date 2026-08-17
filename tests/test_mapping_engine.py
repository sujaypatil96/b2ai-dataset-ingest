"""Mapping engine: rows -> IR fragments."""

from b2ai_dataset_ingest.mapping.engine import MappingEngine


def test_apply_row_returns_list():
    # A minimal mapping with no items/score/columns yields an empty (but non-None) list.
    engine = MappingEngine(mapping={"table": "phq9"})
    result = engine.apply({"participant_id": "ms-0001", "session_id": "ses-baseline"})
    assert result == []


def test_measurements_from_ordinal_scale_fallback():
    # No data dict -> the answer->value map comes from the config's ordinal_scale.
    mapping = {
        "table": "phq9",
        "ordinal_scale": {"Several days": 1, "Not at all": 0},
        "items": {"feeling_depressed": {"id": "LOINC:44255-8", "label": "depressed mood"}},
    }
    engine = MappingEngine(mapping)
    [measurement] = engine.measurements({"feeling_depressed": "Several days"})
    assert measurement.assay.id == "LOINC:44255-8"
    assert measurement.value_quantity.value == 1.0
    assert measurement.value_quantity.unit.id == "UCUM:{score}"


def test_measurements_prefer_data_dict_choices():
    # The data dict's per-item choices override the config ordinal_scale, so an item on a
    # different scale ("Very difficult") maps correctly.
    mapping = {
        "table": "phq9",
        "ordinal_scale": {"Not at all": 0},
        "items": {"hard_to_work": {"id": "LOINC:69722-7", "label": "difficulty working"}},
    }
    data_dict = {
        "hard_to_work": {
            "choices": [
                {"name": {"en": "Not difficult at all"}, "value": 0},
                {"name": {"en": "Very difficult"}, "value": 2},
            ]
        }
    }
    engine = MappingEngine(mapping)
    [measurement] = engine.measurements({"hard_to_work": "Very difficult"}, data_dict)
    assert measurement.value_quantity.value == 2.0


def test_precomputed_total_score():
    mapping = {
        "table": "vhi10",
        "score": {
            "source_column": "vhi_10_calc_score",
            "assay": {"id": "b2ai:vhi10.total", "label": "VHI-10 total"},
            "unit": {"id": "UCUM:{score}", "label": "score"},
        },
    }
    engine = MappingEngine(mapping)
    [measurement] = engine.measurements({"vhi_10_calc_score": "17"})
    assert measurement.assay.id == "b2ai:vhi10.total"
    assert measurement.value_quantity.value == 17.0


def test_individual_fields_recode_and_transform():
    mapping = {
        "produces": "Individual",
        "columns": {
            "age": {"target": "Individual.age_iso8601", "transform": "years_to_iso8601"},
            "sex_assigned_at_birth": {
                "target": "Individual.sex",
                "value_map": {"Male": "MALE"},
            },
        },
    }
    engine = MappingEngine(mapping)
    fields = engine.individual_fields({"age": "63", "sex_assigned_at_birth": "Male"})
    assert fields == {"age_iso8601": "P63Y", "sex": "MALE"}


def test_years_to_iso8601_handles_floats_and_junk():
    assert MappingEngine.years_to_iso8601("54.0") == "P54Y"
    assert MappingEngine.years_to_iso8601("63") == "P63Y"
    assert MappingEngine.years_to_iso8601("synthetic") is None
