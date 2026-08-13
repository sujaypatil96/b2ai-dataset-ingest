"""Reader session-keying against the *real* table shape.

The synthetic tree carries a bare ``session_id``; the real GAD-7 table uses
``gad_7_session_id`` and has no ``session_id`` at all. The reader must key on the
per-instrument column so a participant's repeated visits stay distinct instead of being
collapsed (last-non-empty-wins) into one chimeric row.
"""

import json
import logging
from pathlib import Path

from b2ai_dataset_ingest.sources.voice import VoiceSource

CONFIG_DIR = Path(__file__).parents[1] / "config" / "voice"

_FLAT_GAD7_DICT = {
    "participant_id": {"description": "id", "valueType": ["xsd:string"]},
    "gad_7_session_id": {"description": "session", "valueType": ["xsd:string"]},
    "nervous_anxious": {
        "description": "nervous",
        "datatype": ["xsd:integer"],
        "choices": [
            {"name": {"en": "Not at all"}, "value": 0},
            {"name": {"en": "Several days"}, "value": 1},
            {"name": {"en": "More than half the days"}, "value": 2},
            {"name": {"en": "Nearly every day"}, "value": 3},
        ],
    },
    "tough_to_work": {
        "description": "difficulty",
        "datatype": ["xsd:integer"],
        "choices": [
            {"name": {"en": "Not difficult at all"}, "value": 0},
            {"name": {"en": "Somewhat difficult"}, "value": 1},
            {"name": {"en": "Very difficult"}, "value": 2},
            {"name": {"en": "Extremely difficult"}, "value": 3},
        ],
    },
}


def _write_real_shaped_gad7(root: Path, rows: list[list[str]], header: list[str]) -> None:
    qdir = root / "questionnaire"
    qdir.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(header)] + ["\t".join(r) for r in rows]
    (qdir / "gad7_anxiety.tsv").write_text("\n".join(lines) + "\n")
    (qdir / "gad7_anxiety.json").write_text(json.dumps(_FLAT_GAD7_DICT))


def test_real_session_column_keeps_visits_distinct(tmp_path: Path):
    # Two visits for p1 with DIFFERENT answers, keyed by gad_7_session_id (no session_id).
    _write_real_shaped_gad7(
        tmp_path,
        header=["participant_id", "gad_7_session_id", "nervous_anxious", "tough_to_work"],
        rows=[
            ["p1", "s-aaa", "Several days", "Somewhat difficult"],
            ["p1", "s-bbb", "Nearly every day", "Very difficult"],
        ],
    )
    source = VoiceSource(root=tmp_path, config_dir=CONFIG_DIR)
    [participant] = list(source.read())
    # 2 items x 2 visits = 4 measurements; the visits are NOT merged.
    assert len(participant.measurements) == 4
    assert source.report.rows_merged == 0
    # tough_to_work resolved on its difficulty scale at BOTH visits, distinct values.
    tw = sorted(
        m.value_quantity.value
        for m in participant.measurements
        if m.assay.id == "LOINC:69722-7"
    )
    assert tw == [1.0, 2.0]


def test_same_session_duplicate_rows_merge_without_logging_participant(tmp_path, caplog):
    # Two rows, same gad_7_session_id: a legitimate duplicate -> merged (last-non-empty-wins).
    _write_real_shaped_gad7(
        tmp_path,
        header=["participant_id", "gad_7_session_id", "nervous_anxious", "tough_to_work"],
        rows=[
            ["SECRET-PID", "s-aaa", "Several days", ""],
            ["SECRET-PID", "s-aaa", "", "Very difficult"],
        ],
    )
    source = VoiceSource(root=tmp_path, config_dir=CONFIG_DIR)
    with caplog.at_level(logging.WARNING):
        [participant] = list(source.read())
    # Merged into one timepoint -> 2 items answered across the two rows.
    assert len(participant.measurements) == 2
    assert source.report.rows_merged == 1
    # PHI-safe: the participant id must not appear anywhere in the logs.
    assert "SECRET-PID" not in caplog.text


def test_no_session_column_emits_unmerged_and_is_flagged(tmp_path, caplog):
    # Neither session_id nor gad_7_session_id present: must NOT collapse the two rows.
    _write_real_shaped_gad7(
        tmp_path,
        header=["participant_id", "nervous_anxious", "tough_to_work"],
        rows=[
            ["p9", "Several days", "Somewhat difficult"],
            ["p9", "Nearly every day", "Very difficult"],
        ],
    )
    source = VoiceSource(root=tmp_path, config_dir=CONFIG_DIR)
    with caplog.at_level(logging.ERROR):
        [participant] = list(source.read())
    # Rows kept independent -> 2 items x 2 rows = 4 measurements, nothing merged.
    assert len(participant.measurements) == 4
    assert source.report.rows_merged == 0
    assert "gad7_anxiety" in source.report.tables_without_session
    assert any("no session key" in r.message for r in caplog.records)


def test_unmapped_questionnaire_is_recorded_not_silently_skipped(tmp_path):
    _write_real_shaped_gad7(
        tmp_path,
        header=["participant_id", "gad_7_session_id", "nervous_anxious", "tough_to_work"],
        rows=[["p1", "s-aaa", "Several days", "Somewhat difficult"]],
    )
    # An extra questionnaire on disk with no config. Deliberately a name no config will ever
    # claim — using a real instrument here breaks the test the day that instrument is configured.
    (tmp_path / "questionnaire" / "not_a_configured_instrument.tsv").write_text(
        "participant_id\tx\np1\t1\n"
    )
    source = VoiceSource(root=tmp_path, config_dir=CONFIG_DIR)
    list(source.read())
    assert "not_a_configured_instrument" in source.report.tables_unmapped
