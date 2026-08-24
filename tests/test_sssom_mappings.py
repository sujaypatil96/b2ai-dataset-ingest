"""Validate the shipped B2AI -> HPO SSSOM mappings, and test the validator itself.

Layered like the real-data test in ``test_end_to_end.py``: structural checks always run;
the subject-existence and HPO (oaklib) checks run only when their backend is available and
otherwise ``skip`` -- so the suite is green on a bare checkout but *enforcing* in CI, where
the ``validation`` extra (oaklib) and the fetched synthetic data are present.
"""

from pathlib import Path

import pytest

from b2ai_dataset_ingest.ontology.sssom_validate import (
    _get_hp_adapter,
    default_mapping_files,
    parse_sssom,
    validate_paths,
)

REPO = Path(__file__).parents[1]
MAPPING_FILES = default_mapping_files(REPO)

# Candidate phenotype roots for the subject-existence check (first that exists wins): the
# fetched synthetic tree (CI) or the local real-data dictionaries.
# Synthetic only: the test suite reads from data_synth/, never from the source datasets
# under data/ (which may be owned by a separate account and unreadable here anyway).
DATA_ROOTS = [
    REPO / "data_synth" / "b2ai-voice-synthetic-phenotype" / "output" / "phenotype",
]

SSSOM_HEADER = (
    "# curie_map:\n"
    "#   b2ai: https://github.com/sujaypatil96/b2ai-dataset-ingest#\n"
    "#   HP: http://purl.obolibrary.org/obo/HP_\n"
    "#   skos: http://www.w3.org/2004/02/skos/core#\n"
    "#   semapv: https://w3id.org/semapv/vocab/\n"
    "# license: https://creativecommons.org/publicdomain/zero/1.0/\n"
)
SSSOM_COLS = (
    "subject_id\tsubject_label\tpredicate_id\tobject_id\tobject_label\t"
    "mapping_justification\tconfidence\tcomment"
)


def _data_root() -> Path | None:
    return next((p for p in DATA_ROOTS if p.exists()), None)


def _oaklib_ready() -> bool:
    return _get_hp_adapter() is not None


def _sssom_ready() -> bool:
    try:
        import sssom.parsers  # noqa: F401
        import sssom.validators  # noqa: F401

        return True
    except ImportError:
        return False


def _row(subject: str, predicate: str, obj: str, obj_label: str, confidence: str = "0.9") -> str:
    """Build one TSV row (label/justification/comment filled with sensible defaults)."""
    return "\t".join(
        [subject, "x", predicate, obj, obj_label, "semapv:ManualMappingCuration", confidence, ""]
    )


def _write_sssom(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "case.sssom.tsv"
    path.write_text(SSSOM_HEADER + SSSOM_COLS + "\n" + "\n".join(rows) + "\n")
    return path


# --------------------------------------------------------------- the shipped mappings


def test_mapping_files_present():
    assert MAPPING_FILES, "no SSSOM mapping files shipped under mappings/"


@pytest.mark.parametrize("path", MAPPING_FILES, ids=lambda p: p.name)
def test_parses_and_structural(path: Path):
    metadata, rows = parse_sssom(path)
    assert metadata.get("curie_map"), f"{path.name} missing curie_map metadata"
    assert rows, f"{path.name} has no mappings"
    result = validate_paths([path], data_root=None, check_ontology=False)
    assert not result.errors, "\n".join(f.render() for f in result.errors)


@pytest.mark.skipif(_data_root() is None, reason="no phenotype data root available")
def test_subjects_exist_in_data_dicts():
    result = validate_paths(MAPPING_FILES, data_root=_data_root(), check_ontology=False)
    unknown = [f for f in result.errors if f.code == "unknown-column"]
    assert not unknown, "\n".join(f.render() for f in unknown)


@pytest.mark.skipif(not _sssom_ready(), reason="sssom-py not installed")
@pytest.mark.parametrize("path", MAPPING_FILES, ids=lambda p: p.name)
def test_official_sssom_schema_validation(path: Path):
    """Cross-check against the reference sssom-py validator (JSON-schema + prefix declarations)."""
    from sssom.parsers import parse_sssom_table
    from sssom.validators import DEFAULT_VALIDATION_TYPES, validate

    validate(parse_sssom_table(str(path)), DEFAULT_VALIDATION_TYPES)  # raises on any violation


@pytest.mark.skipif(not _oaklib_ready(), reason="oaklib/HPO backend unavailable")
def test_no_hallucinated_hpo_terms():
    result = validate_paths(MAPPING_FILES, data_root=None, check_ontology=True)
    assert result.ontology_checked
    assert not result.errors, "\n".join(f.render() for f in result.errors)


# ------------------------------------------------------------- the validator itself


def test_validator_catches_structural_faults(tmp_path: Path):
    """Offline negative control: malformed rows must be rejected without any backend."""
    path = _write_sssom(
        tmp_path,
        [
            _row("not_a_b2ai_subject", "skos:exactMatch", "HP:0001513", "Obesity"),
            _row("b2ai:no_dot_subject", "skos:exactMatch", "HP:0001513", "Obesity"),
            _row("b2ai:confounders.obesity", "skos:sameAs", "MONDO:0011122", "Obesity"),
            _row("b2ai:confounders.scoliosis", "skos:exactMatch", "HP:0002650", "Scoliosis", "5"),
        ],
    )
    codes = {f.code for f in validate_paths([path], check_ontology=False).errors}
    expected = {"bad-subject", "malformed-subject", "bad-predicate", "bad-object", "bad-confidence"}
    assert expected <= codes


_COND_COLS = (
    "subject_id\tsubject_label\tpredicate_id\tobject_id\tobject_label\t"
    "mapping_justification\tconfidence\tpredicate_modifier\twhen_value"
)


def _cond_row(subject, obj, obj_label, modifier="", when=""):
    return "\t".join(
        [subject, "x", "skos:broadMatch", obj, obj_label,
         "semapv:ManualMappingCuration", "0.8", modifier, when]
    )


def _write_conditional(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "cond.sssom.tsv"
    path.write_text(SSSOM_HEADER + _COND_COLS + "\n" + "\n".join(rows) + "\n")
    return path


def test_interpretation_columns_are_rejected_in_a_mapping_set(tmp_path: Path):
    """ADR-0003: `when_value`/`predicate_modifier` belong in mappings/derivations/, not here.

    They are rejected rather than ignored because `predicate_modifier: Not` negates *the
    mapping* per the SSSOM spec ("subject is not a predicate match to object"), so a
    present/absent pair on one triple asserts a contradiction, not phenotype absence.
    """
    path = _write_conditional(
        tmp_path,
        [
            _cond_row("b2ai:phq9.feeling_depressed", "HP:0000716", "Depression", modifier="Not"),
            _cond_row("b2ai:phq9.no_energy", "HP:0012378", "Fatigue", when=">=1"),
        ],
    )
    findings = validate_paths([path], check_ontology=False).errors
    assert {f.code for f in findings} >= {"interpretation-in-mapping"}
    offenders = {f.subject for f in findings if f.code == "interpretation-in-mapping"}
    assert offenders == {"b2ai:phq9.feeling_depressed", "b2ai:phq9.no_energy"}


def test_one_triple_one_row(tmp_path: Path):
    """With the poles gone there is no present/absent pair to exempt: a repeated
    (subject, predicate, object) is simply a duplicate."""
    dup = _write_conditional(
        tmp_path,
        [
            _cond_row("b2ai:phq9.feeling_depressed", "HP:0000716", "Depression"),
            _cond_row("b2ai:phq9.feeling_depressed", "HP:0000716", "Depression"),
        ],
    )
    codes = {f.code for f in validate_paths([dup], check_ontology=False).errors}
    assert "duplicate" in codes


def test_shipped_mapping_sets_carry_no_interpretation_columns():
    """The regression guard for the split itself."""
    for path in default_mapping_files():
        _, rows = parse_sssom(path)
        for row in rows:
            assert "when_value" not in row, f"{path.name} still carries when_value"
            assert "predicate_modifier" not in row, f"{path.name} still carries predicate_modifier"


def test_validator_requires_self_contained_curie_map(tmp_path: Path):
    """A prefix used in a row but absent from the file's own curie_map is an error (L1)."""
    # The header declares b2ai/HP/skos/semapv; MONDO is not declared here.
    path = _write_sssom(
        tmp_path, [_row("b2ai:confounders.obesity", "skos:exactMatch", "HP:0001513", "Obesity")]
    )
    text = path.read_text().replace("HP:0001513", "MONDO:0011122").replace(
        "\tHP:", "\tMONDO:"
    )
    path.write_text(text)
    codes = {f.code for f in validate_paths([path], check_ontology=False).errors}
    assert "unknown-prefix" in codes


@pytest.mark.skipif(not _oaklib_ready(), reason="oaklib/HPO backend unavailable")
def test_validator_catches_hpo_faults(tmp_path: Path):
    """oaklib negative control: fake CURIE, drifted label, and a deprecated term must be caught."""
    path = _write_sssom(
        tmp_path,
        [
            _row("b2ai:confounders.dizziness", "skos:exactMatch", "HP:9999999", "Made up"),
            _row("b2ai:confounders.ataxia", "skos:exactMatch", "HP:0001251", "Parkinsonism"),
            # HP:0007815 is deprecated but keeps a normal (non-"obsolete ") label -- the
            # label-heuristic hole; must be caught via owl:deprecated / adapter.obsoletes().
            _row(
                "b2ai:confounders.foo", "skos:exactMatch", "HP:0007815",
                "Abnormal distribution of retinal arterioles and venules",
            ),
        ],
    )
    codes = {f.code for f in validate_paths([path], check_ontology=True).errors}
    assert "hallucinated-term" in codes
    assert "label-mismatch" in codes
    assert "obsolete-term" in codes


@pytest.mark.skipif(not _oaklib_ready(), reason="oaklib/HPO backend unavailable")
def test_exact_synonym_warns_but_related_synonym_errors(tmp_path: Path):
    """An exact HPO synonym as object_label only warns; a related synonym is an error (L2)."""
    path = _write_sssom(
        tmp_path,
        [
            # "Shortness of breath" is an EXACT synonym of HP:0002094 Dyspnea -> warning
            _row("b2ai:confounders.shortness_breath", "skos:exactMatch", "HP:0002094", "Shortness of breath"),  # noqa: E501
            # "Panting" is a RELATED synonym only -> error
            _row("b2ai:confounders.baz", "skos:closeMatch", "HP:0002094", "Panting"),
        ],
    )
    result = validate_paths([path], check_ontology=True)
    assert {f.code for f in result.warnings} & {"noncanonical-label"}
    assert "label-mismatch" in {f.code for f in result.errors}
