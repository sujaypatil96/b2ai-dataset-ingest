"""Preflight validation: it must catch the drift that would otherwise fail silently."""

import json
from pathlib import Path

from b2ai_dataset_ingest.sources.voice.validate import validate_voice

CONFIG_DIR = Path(__file__).parents[1] / "config" / "voice"

_FLAT_DICT = {
    "participant_id": {"description": "id", "valueType": ["xsd:string"]},
    "gad_7_session_id": {"description": "session", "valueType": ["xsd:string"]},
    "nervous_anxious": {
        "description": "nervous",
        "datatype": ["xsd:integer"],
        "choices": [
            {"name": {"en": "Not at all"}, "value": 0},
            {"name": {"en": "Several days"}, "value": 1},
        ],
    },
}


def _write_gad7(root: Path, header: list[str], rows: list[list[str]], dict_obj=_FLAT_DICT):
    qdir = root / "questionnaire"
    qdir.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(header)] + ["\t".join(r) for r in rows]
    (qdir / "gad7_anxiety.tsv").write_text("\n".join(lines) + "\n")
    if dict_obj is not None:
        (qdir / "gad7_anxiety.json").write_text(json.dumps(dict_obj))


def test_missing_session_column_is_an_error(tmp_path: Path):
    _write_gad7(tmp_path, header=["participant_id", "nervous_anxious"], rows=[["p1", "Not at all"]])
    report = validate_voice(tmp_path, CONFIG_DIR)
    assert any("session_columns" in f.message for f in report.errors)


def test_mapped_column_absent_is_an_error(tmp_path: Path):
    # gad7 config maps 8 items; a table with only nervous_anxious is missing the rest.
    _write_gad7(
        tmp_path,
        header=["participant_id", "gad_7_session_id", "nervous_anxious"],
        rows=[["p1", "s-a", "Not at all"]],
    )
    report = validate_voice(tmp_path, CONFIG_DIR)
    assert any("absent from header" in f.message for f in report.errors)


def test_unrecognized_dict_envelope_is_an_error(tmp_path: Path):
    _write_gad7(
        tmp_path,
        header=["participant_id", "gad_7_session_id", "nervous_anxious"],
        rows=[["p1", "s-a", "Not at all"]],
        dict_obj={"totally": "unexpected", "shape": 1},
    )
    report = validate_voice(tmp_path, CONFIG_DIR)
    assert any("envelope was unrecognized" in f.message for f in report.errors)


def test_clean_real_shaped_table_has_no_session_or_column_errors(tmp_path: Path):
    full_header = [
        "participant_id",
        "gad_7_session_id",
        "nervous_anxious",
        "cant_control_worry",
        "worry_too_much",
        "trouble_relaxing",
        "hard_to_sit_still",
        "easily_agitated",
        "afraid_of_things",
        "tough_to_work",
    ]
    _write_gad7(tmp_path, header=full_header, rows=[["p1", "s-a"] + ["Not at all"] * 8])
    report = validate_voice(tmp_path, CONFIG_DIR)
    # No "absent from header" and no session errors for the fully-shaped table.
    assert not any("absent from header" in f.message for f in report.errors)
    assert not any("session_columns" in f.message for f in report.errors)


def test_unmapped_questionnaire_is_a_warning_not_error(tmp_path: Path):
    _write_gad7(
        tmp_path,
        header=["participant_id", "gad_7_session_id", "nervous_anxious"],
        rows=[["p1", "s-a", "Not at all"]],
    )
    (tmp_path / "questionnaire" / "panas.tsv").write_text("participant_id\tx\np1\t1\n")
    report = validate_voice(tmp_path, CONFIG_DIR)
    assert any(f.table == "panas" and f.level == "warning" for f in report.findings)
