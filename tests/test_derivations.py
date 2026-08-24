"""Loading ``mappings/derivations/*.yaml`` into executable rules."""

import logging
from pathlib import Path

from b2ai_dataset_ingest.mapping.derivations import (
    default_derivation_files,
    load_derivation_rules,
)

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
{poles}"""


def _write(tmp_path: Path, rules: str) -> Path:
    path = tmp_path / "phq9.yaml"
    path.write_text(DOC.format(rules=rules))
    return path


def test_both_poles_become_rules(tmp_path: Path):
    path = _write(
        tmp_path,
        RULE.format(
            subject="b2ai:phq9.no_interest",
            obj="HP:0012154",
            poles='    present:\n      when_value: ">=1"\n    absent:\n      when_value: "==0"\n',
        ),
    )
    rules = load_derivation_rules([path])["phq9"]["no_interest"]
    assert {r.when_value for r in rules} == {">=1", "==0"}
    assert [r.excluded for r in sorted(rules, key=lambda r: r.when_value)] == [True, False]


def test_unauthorable_pole_yields_no_rule(tmp_path: Path):
    """A declined pole is a recorded decision, not a gap — it must derive nothing."""
    path = _write(
        tmp_path,
        RULE.format(
            subject="b2ai:phq9.trouble_sleeping",
            obj="HP:0002360",
            poles=(
                '    present:\n      when_value: ">=1"\n'
                "    absent:\n      unauthorable: conflated-superset\n      note: broader\n"
            ),
        ),
    )
    [rule] = load_derivation_rules([path])["phq9"]["trouble_sleeping"]
    assert rule.pole == "present"


def test_rules_carry_the_instrument_recall_window(tmp_path: Path):
    path = _write(
        tmp_path,
        RULE.format(
            subject="b2ai:phq9.no_interest",
            obj="HP:0012154",
            poles='    present:\n      when_value: ">=1"\n',
        ),
    )
    [rule] = load_derivation_rules([path])["phq9"]["no_interest"]
    assert rule.window.iso8601 == "P2W"
    assert rule.window.source == "data_dict"
    assert rule.window.is_known
    assert rule.instrument_label == "Patient Health Questionnaire-9 (PHQ-9)"


def test_malformed_rules_are_skipped_with_warning(tmp_path: Path, caplog):
    path = _write(
        tmp_path,
        RULE.format(
            subject="not-a-b2ai-subject",
            obj="HP:0012154",
            poles='    present:\n      when_value: ">=1"\n',
        )
        + RULE.format(
            subject="b2ai:phq9.thoughts_death",
            obj="MONDO:0000001",
            poles='    present:\n      when_value: ">=1"\n',
        )
        + RULE.format(
            subject="b2ai:phq9.no_energy",
            obj="HP:0012378",
            poles='    present:\n      when_value: "totally bogus"\n',
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert load_derivation_rules([path]) == {}
    assert "malformed subject" in caplog.text
    assert "non-HPO object" in caplog.text
    assert "unparseable when_value" in caplog.text


def test_unreadable_file_is_skipped_with_warning(tmp_path: Path, caplog):
    path = tmp_path / "broken.yaml"
    path.write_text("instrument: phq9\nrules: [oops\n")
    with caplog.at_level(logging.WARNING):
        assert load_derivation_rules([path]) == {}
    assert "unreadable derivation file" in caplog.text


def test_shipped_rule_files_load():
    """The rules that ship must actually load — a YAML typo would silently derive nothing."""
    index = load_derivation_rules()
    assert default_derivation_files(), "no derivation files are shipped"
    assert set(index) >= {"phq9", "gad7_anxiety", "dsm5_adult", "ptsd_adult"}
    assert index["phq9"]["no_interest"], "PHQ-9 anhedonia rule did not load"
