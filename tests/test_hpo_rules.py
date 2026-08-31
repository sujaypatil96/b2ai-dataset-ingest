"""Value-gated B2AI -> HPO rules: loading conditional mappings and deriving features."""

import logging
from pathlib import Path

from b2ai_dataset_ingest.mapping.conditions import parse_condition
from b2ai_dataset_ingest.mapping.hpo_rules import (
    SELF_REPORT_EVIDENCE,
    ConditionalRule,
    derive_features,
    load_conditional_rules,
)
from b2ai_dataset_ingest.model import TimePoint
from b2ai_dataset_ingest.reporting import IngestReport

HEADER = (
    "# curie_map:\n"
    "#   b2ai: https://github.com/sujaypatil96/b2ai-dataset-ingest#\n"
    "#   HP: http://purl.obolibrary.org/obo/HP_\n"
    "#   skos: http://www.w3.org/2004/02/skos/core#\n"
    "#   semapv: https://w3id.org/semapv/vocab/\n"
    "# license: https://creativecommons.org/publicdomain/zero/1.0/\n"
)
COLS = (
    "subject_id\tsubject_label\tpredicate_id\tobject_id\tobject_label\t"
    "mapping_justification\tconfidence\twhen_value"
)


def _row(subject, obj, *, when="", label="x", obj_label="Depression", conf="0.8"):
    return "\t".join(
        [subject, label, "skos:broadMatch", obj, obj_label,
         "semapv:ManualMappingCuration", conf, when]
    )


def _write(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "q.sssom.tsv"
    path.write_text(HEADER + COLS + "\n" + "\n".join(rows) + "\n")
    return path


# ------------------------------------------------------------------------- loading


def test_only_rows_with_when_value_become_rules(tmp_path: Path):
    path = _write(
        tmp_path,
        [
            _row("b2ai:phq9.feeling_depressed", "HP:0000716", when=">=1"),
            _row("b2ai:phq9.no_interest", "HP:0012154"),  # inert (no when_value) -> ignored
        ],
    )
    index = load_conditional_rules([path])
    assert set(index["phq9"]) == {"feeling_depressed"}  # no_interest carried no condition
    assert [r.when_value for r in index["phq9"]["feeling_depressed"]] == [">=1"]


def test_malformed_rows_are_skipped_with_warning(tmp_path: Path, caplog):
    path = _write(
        tmp_path,
        [
            _row("not-a-b2ai-subject", "HP:0000716", when=">=1"),
            _row("b2ai:phq9.thoughts_death", "MONDO:0000001", when=">=1"),  # non-HPO object
            _row("b2ai:phq9.no_energy", "HP:0012378", when="totally bogus"),  # unparseable
        ],
    )
    with caplog.at_level(logging.WARNING):
        index = load_conditional_rules([path])
    assert index == {}  # every row rejected
    assert "malformed subject" in caplog.text
    assert "non-HPO object" in caplog.text
    assert "unparseable when_value" in caplog.text


# ---------------------------------------------------------------------- derivation

_SCALE = {"Not at all": 0, "Several days": 1, "Nearly every day": 3}


def _RESOLVE(column: str, raw: str) -> int | None:
    """Test stand-in for the engine's ordinal resolution: (column, raw) -> score."""
    return _SCALE.get(raw)


def _rule(**kw) -> ConditionalRule:
    defaults = dict(
        subject_id="b2ai:phq9.feeling_depressed",
        table="phq9",
        column="feeling_depressed",
        object_id="HP:0000716",
        object_label="Depression",
        predicate_id="skos:broadMatch",
        condition=parse_condition(">=1"),
        when_value=">=1",
        subject_label="Feeling down, depressed, or hopeless",
        confidence="0.8",
    )
    defaults.update(kw)
    return ConditionalRule(**defaults)


def test_present_pole_derives_feature_with_provenance():
    rules = {"feeling_depressed": [_rule()]}
    time = TimePoint(session_id="ses-baseline")
    report = IngestReport()
    [feature] = derive_features(
        {"feeling_depressed": "Several days"}, rules, _RESOLVE, time, report
    )
    assert feature.type.id == "HP:0000716"
    assert feature.excluded is False
    assert feature.onset is time
    assert report.features_derived == 1
    # Provenance: a human-readable description + an ECO self-report Evidence to the source item.
    assert "feeling_depressed" in feature.description
    assert ">=1" in feature.description
    [evidence] = feature.evidence
    assert evidence.evidence_code == SELF_REPORT_EVIDENCE
    assert evidence.reference.id == "b2ai:phq9.feeling_depressed"
    assert evidence.reference.reference.endswith("#phq9.feeling_depressed")


def test_derived_features_only_ever_assert_presence():
    """A questionnaire's lowest answer denies the symptom within the instrument's recall window,
    not the phenotype, so no rule can produce ``excluded`` (clinical review, 2026-08-24)."""
    rules = {"feeling_depressed": [_rule(condition=parse_condition("<=1"), when_value="<=1")]}
    [feature] = derive_features({"feeling_depressed": "Not at all"}, rules, _RESOLVE)
    assert feature.excluded is False
    assert "Derived present" in feature.description


def test_blank_and_unmatched_cells_assert_nothing():
    rules = {"feeling_depressed": [_rule()]}  # gate is >=1
    assert derive_features({"feeling_depressed": ""}, rules, _RESOLVE) == []
    assert derive_features({}, rules, _RESOLVE) == []
    assert derive_features({"feeling_depressed": "Not at all"}, rules, _RESOLVE) == []
