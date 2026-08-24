"""Reader -> derived HPO PhenotypicFeatures, end to end (ADR-0003).

Exercises the whole apply path against a hermetic PHQ-9 slice and an injected derivation-rule
file carrying both poles, then round-trips through the emitter. The absent pole is authored
here exactly as it ships, so this also pins the current end-to-end behaviour: because the
reader can give a session no timestamp, the absent pole is *withheld* rather than published
as unqualified absence. (``tests/test_hpo_rules.py`` covers the other side of that gate — the
same rule deriving a bounded exclusion once an observation time exists.)
"""

from pathlib import Path

import phenopackets as pp
from google.protobuf.json_format import Parse

from b2ai_dataset_ingest.emitters import PhenopacketEmitter
from b2ai_dataset_ingest.sources.voice import VoiceSource

CONFIG_DIR = Path(__file__).parents[1] / "config" / "voice"

_RULES = """\
instrument: phq9
label: Patient Health Questionnaire-9 (PHQ-9)
recall_window:
  iso8601: P2W
  text: over the last 2 weeks
  source: data_dict
scoring_reference: test fixture
rules:
  - subject_id: b2ai:phq9.feeling_depressed
    object_id: HP:0000716
    object_label: Depression
    confidence: 0.8
    present:
      when_value: ">=1"
    absent:
      when_value: "==0"
"""


def _build_dataset(root: Path) -> Path:
    qdir = root / "questionnaire"
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "phq9.tsv").write_text(
        "participant_id\tsession_id\tfeeling_depressed\n"
        "p1\tses-baseline\tSeveral days\n"  # -> present at baseline
        "p1\tses-followup\tNot at all\n"  # -> absent pole matches, but cannot be scoped
        "p2\tses-baseline\t\n"  # blank -> nothing asserted
    )
    rules = root / "phq9.yaml"
    rules.write_text(_RULES)
    return rules


def _source(tmp_path: Path) -> VoiceSource:
    return VoiceSource(root=tmp_path, config_dir=CONFIG_DIR, mappings=[_build_dataset(tmp_path)])


def test_present_pole_is_derived_and_unscopable_absence_is_withheld(tmp_path: Path):
    source = _source(tmp_path)
    participants = {p.individual.id: p for p in source.read()}

    p1 = participants["p1"]
    by_session = {(f.onset.session_id if f.onset else None): f for f in p1.phenotypic_features}
    assert set(by_session) == {"ses-baseline"}
    assert by_session["ses-baseline"].type.id == "HP:0000716"
    assert by_session["ses-baseline"].excluded is False

    # "Not at all" at followup matched the absent rule, but a session with no timestamp gives
    # the exclusion no period to be true over, so nothing is asserted -- and the skip is counted.
    assert source.report.absent_features_unscoped == 1

    # A blank answer asserts nothing.
    assert participants["p2"].phenotypic_features == []

    assert source.report.features_derived == 1


def test_no_excluded_features_are_emitted_from_the_shipped_pipeline(tmp_path: Path):
    """The guarantee the clinical review asked for: no unqualified absence reaches the output."""
    source = _source(tmp_path)
    for participant in source.read():
        assert not any(f.excluded for f in participant.phenotypic_features)


def test_derived_feature_carries_self_report_evidence(tmp_path: Path):
    source = _source(tmp_path)
    p1 = next(p for p in source.read() if p.individual.id == "p1")
    feature = p1.phenotypic_features[0]
    [evidence] = feature.evidence
    assert evidence.evidence_code.id == "ECO:0006160"
    assert evidence.reference.id == "b2ai:phq9.feeling_depressed"
    assert feature.description  # non-empty human-readable provenance
    assert "over the last 2 weeks" in feature.description  # the window is carried, not implied


def test_derived_features_roundtrip_through_emitter(tmp_path: Path):
    source = _source(tmp_path)
    participants = list(source.read())
    written = PhenopacketEmitter().write_all(participants, tmp_path / "out")
    assert written == 2

    parsed = Parse((tmp_path / "out" / "p1.json").read_text(), pp.Phenopacket())
    assert len(parsed.phenotypic_features) == 1
    declared = {r.namespace_prefix for r in parsed.meta_data.resources}
    # The self-report provenance pulls in ECO + the b2ai source-item reference + HP.
    assert {"HP", "ECO", "b2ai"} <= declared


def test_no_rules_means_no_features(tmp_path: Path):
    # With an empty rule list the pipeline is unchanged: measurements only, no features.
    _build_dataset(tmp_path)
    source = VoiceSource(root=tmp_path, config_dir=CONFIG_DIR, mappings=[])
    participants = list(source.read())
    assert all(p.phenotypic_features == [] for p in participants)
    assert source.report.features_derived == 0
    assert any(p.measurements for p in participants)  # measurements still emitted
