"""Loading derivation rules from their two homes: SSSOM `when_value` + instrument files."""

import logging
from pathlib import Path

from b2ai_dataset_ingest.mapping.derivations import (
    default_derivation_files,
    load_derivation_rules,
)

# -- an instrument file: absent poles + the window both poles are stamped with --
DOC = """
instrument: phq9
label: Patient Health Questionnaire-9 (PHQ-9)
recall_window:
  iso8601: P2W
  text: over the last 2 weeks
  source: data_dict
scoring_reference: somewhere
rules:
{rules}
"""

RULE = """  - subject_id: {subject}
    object_id: {obj}
    object_label: Anhedonia
    confidence: 0.9
    absent:
{pole}"""

# -- a mapping set: the present pole rides on the row it qualifies --
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
    "mapping_justification\tconfidence\tcomment\twhen_value"
)


def _mapping(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    """rows are (subject, object, when_value)."""
    body = "\n".join(
        "\t".join([s, "x", "skos:exactMatch", o, "Anhedonia",
                   "semapv:ManualMappingCuration", "0.9", "", w])
        for s, o, w in rows
    )
    path = tmp_path / "q.sssom.tsv"
    path.write_text(SSSOM_HEADER + SSSOM_COLS + "\n" + body + "\n")
    return path


def _rules(tmp_path: Path, rules: str) -> Path:
    path = tmp_path / "phq9.yaml"
    path.write_text(DOC.format(rules=rules))
    return path


def test_present_comes_from_the_mapping_and_absent_from_the_instrument_file(tmp_path: Path):
    files = [
        _mapping(tmp_path, [("b2ai:phq9.no_interest", "HP:0012154", ">=1")]),
        _rules(tmp_path, RULE.format(
            subject="b2ai:phq9.no_interest", obj="HP:0012154",
            pole='      when_value: "==0"\n')),
    ]
    rules = load_derivation_rules(files)["phq9"]["no_interest"]
    assert {(r.pole, r.when_value) for r in rules} == {("present", ">=1"), ("absent", "==0")}


def test_empty_when_value_is_a_pure_semantic_mapping(tmp_path: Path):
    """A mapping with no gate derives nothing — it only records aboutness."""
    path = _mapping(tmp_path, [("b2ai:phq9.no_interest", "HP:0012154", "")])
    assert load_derivation_rules([path]) == {}


def test_unauthorable_absent_pole_yields_no_rule(tmp_path: Path):
    """A declined pole is a recorded decision, not a gap — it must derive nothing."""
    files = [
        _mapping(tmp_path, [("b2ai:phq9.trouble_sleeping", "HP:0002360", ">=1")]),
        _rules(tmp_path, RULE.format(
            subject="b2ai:phq9.trouble_sleeping", obj="HP:0002360",
            pole="      unauthorable: conflated-superset\n      note: broader\n")),
    ]
    [rule] = load_derivation_rules(files)["phq9"]["trouble_sleeping"]
    assert rule.pole == "present"


def test_a_present_block_in_a_rule_file_is_ignored_not_honoured(tmp_path: Path):
    """It belongs in the SSSOM row; the validator errors on it, the loader must not obey it."""
    path = tmp_path / "phq9.yaml"
    path.write_text(DOC.format(rules=(
        "  - subject_id: b2ai:phq9.no_interest\n"
        "    object_id: HP:0012154\n"
        '    present:\n      when_value: ">=1"\n'
    )))
    assert load_derivation_rules([path]) == {}


def test_both_poles_carry_the_instrument_recall_window(tmp_path: Path):
    """The present pole borrows the window from the instrument file even though it is
    authored in the mapping set — that is what puts the scope in its provenance."""
    files = [
        _mapping(tmp_path, [("b2ai:phq9.no_interest", "HP:0012154", ">=1")]),
        _rules(tmp_path, RULE.format(
            subject="b2ai:phq9.no_interest", obj="HP:0012154",
            pole='      when_value: "==0"\n')),
    ]
    for rule in load_derivation_rules(files)["phq9"]["no_interest"]:
        assert rule.window.iso8601 == "P2W"
        assert rule.window.source == "data_dict"
        assert rule.window.is_known
        assert rule.instrument_label == "Patient Health Questionnaire-9 (PHQ-9)"


def test_present_pole_without_an_instrument_file_still_derives(tmp_path: Path):
    """Degraded, not dropped: no window, but the mapping's own gate still applies."""
    path = _mapping(tmp_path, [("b2ai:phq9.no_interest", "HP:0012154", ">=1")])
    [rule] = load_derivation_rules([path])["phq9"]["no_interest"]
    assert rule.pole == "present"
    assert rule.window.is_known is False


def test_malformed_mapping_rows_are_skipped_with_warning(tmp_path: Path, caplog):
    path = _mapping(tmp_path, [
        ("not-a-b2ai-subject", "HP:0012154", ">=1"),
        ("b2ai:phq9.thoughts_death", "MONDO:0000001", ">=1"),
        ("b2ai:phq9.no_energy", "HP:0012378", "totally bogus"),
    ])
    with caplog.at_level(logging.WARNING):
        assert load_derivation_rules([path]) == {}
    assert "malformed subject" in caplog.text
    assert "non-HPO object" in caplog.text
    assert "unparseable when_value" in caplog.text


def test_malformed_rule_files_are_skipped_with_warning(tmp_path: Path, caplog):
    path = tmp_path / "broken.yaml"
    path.write_text("instrument: phq9\nrules: [oops\n")
    with caplog.at_level(logging.WARNING):
        assert load_derivation_rules([path]) == {}
    assert "unreadable derivation file" in caplog.text


def test_a_broken_sssom_header_is_reported_not_silent(tmp_path: Path, caplog):
    """A stray ': ' in the metadata comment once disabled every present pole in the file
    while the run still looked green. It must warn."""
    path = _mapping(tmp_path, [("b2ai:phq9.no_interest", "HP:0012154", ">=1")])
    broken = path.read_text().replace("# license:", "# comment: broken: like this\n# license:")
    path.write_text(broken)
    with caplog.at_level(logging.WARNING):
        assert load_derivation_rules([path]) == {}
    assert "unreadable mapping set" in caplog.text


def test_shipped_files_load_from_both_layers():
    """A YAML typo or a broken SSSOM header would silently derive nothing."""
    index = load_derivation_rules()
    assert default_derivation_files(), "no instrument files are shipped"
    poles = [r.pole for cols in index.values() for rules in cols.values() for r in rules]
    assert poles.count("present") == 36
    assert poles.count("absent") == 26
    assert {r.pole for r in index["phq9"]["no_interest"]} == {"present", "absent"}
