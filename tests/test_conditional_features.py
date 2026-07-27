"""Reader -> value-gated HPO PhenotypicFeatures, end to end (ADR-0002).

Exercises the whole apply path against a hermetic PHQ-9 slice and an injected SSSOM mapping
carrying the worked-example present/absent condition, then round-trips through the emitter.
"""

from pathlib import Path

import phenopackets as pp
from google.protobuf.json_format import Parse

from b2ai_dataset_ingest.emitters import PhenopacketEmitter
from b2ai_dataset_ingest.sources.voice import VoiceSource

CONFIG_DIR = Path(__file__).parents[1] / "config" / "voice"

_MAPPING_HEADER = """\
# curie_map:
#   b2ai: https://github.com/sujaypatil96/b2ai-dataset-ingest#
#   HP: http://purl.obolibrary.org/obo/HP_
#   skos: http://www.w3.org/2004/02/skos/core#
#   semapv: https://w3id.org/semapv/vocab/
# license: https://creativecommons.org/publicdomain/zero/1.0/
# extension_definitions:
#   - slot_name: when_value
#     property: b2ai:when_value
#     type_hint: xsd:string
"""

_COLS = [
    "subject_id", "subject_label", "predicate_id", "object_id", "object_label",
    "mapping_justification", "confidence", "predicate_modifier", "when_value",
]


def _mapping_row(modifier: str, when: str) -> str:
    return "\t".join(
        ["b2ai:phq9.feeling_depressed", "Feeling down", "skos:broadMatch", "HP:0000716",
         "Depression", "semapv:ManualMappingCuration", "0.8", modifier, when]
    )


_MAPPING = (
    _MAPPING_HEADER
    + "\t".join(_COLS) + "\n"
    + _mapping_row("", ">=1") + "\n"        # present pole
    + _mapping_row("Not", "==0") + "\n"     # absent pole
)


def _build_dataset(root: Path) -> Path:
    qdir = root / "questionnaire"
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "phq9.tsv").write_text(
        "participant_id\tsession_id\tfeeling_depressed\n"
        "p1\tses-baseline\tSeveral days\n"   # -> present at baseline
        "p1\tses-followup\tNot at all\n"     # -> excluded at followup
        "p2\tses-baseline\t\n"               # blank -> nothing asserted
    )
    mapping = root / "b2ai-voice-questionnaires.sssom.tsv"
    mapping.write_text(_MAPPING)
    return mapping


def _source(tmp_path: Path) -> VoiceSource:
    mapping = _build_dataset(tmp_path)
    return VoiceSource(root=tmp_path, config_dir=CONFIG_DIR, mappings=[mapping])


def test_present_and_absent_features_across_sessions(tmp_path: Path):
    source = _source(tmp_path)
    participants = {p.individual.id: p for p in source.read()}

    p1 = participants["p1"]
    by_session = {
        (f.onset.session_id if f.onset else None): f for f in p1.phenotypic_features
    }
    assert set(by_session) == {"ses-baseline", "ses-followup"}
    assert by_session["ses-baseline"].type.id == "HP:0000716"
    assert by_session["ses-baseline"].excluded is False
    assert by_session["ses-followup"].excluded is True  # "Not at all" -> absent pole

    # A blank answer asserts nothing.
    assert participants["p2"].phenotypic_features == []

    # The report counts the two derived features.
    assert source.report.features_derived == 2


def test_derived_feature_carries_self_report_evidence(tmp_path: Path):
    source = _source(tmp_path)
    p1 = next(p for p in source.read() if p.individual.id == "p1")
    feature = p1.phenotypic_features[0]
    [evidence] = feature.evidence
    assert evidence.evidence_code.id == "ECO:0006160"
    assert evidence.reference.id == "b2ai:phq9.feeling_depressed"
    assert feature.description  # non-empty human-readable provenance


def test_derived_features_roundtrip_through_emitter(tmp_path: Path):
    source = _source(tmp_path)
    participants = list(source.read())
    written = PhenopacketEmitter().write_all(participants, tmp_path / "out")
    assert written == 2

    parsed = Parse((tmp_path / "out" / "p1.json").read_text(), pp.Phenopacket())
    assert len(parsed.phenotypic_features) == 2
    declared = {r.namespace_prefix for r in parsed.meta_data.resources}
    # The self-report provenance pulls in ECO + the b2ai source-item reference + HP.
    assert {"HP", "ECO", "b2ai"} <= declared


def test_no_mappings_means_no_features(tmp_path: Path):
    # With an empty mappings list the pipeline is unchanged: measurements only, no features.
    _build_dataset(tmp_path)
    source = VoiceSource(root=tmp_path, config_dir=CONFIG_DIR, mappings=[])
    participants = list(source.read())
    assert all(p.phenotypic_features == [] for p in participants)
    assert source.report.features_derived == 0
    assert any(p.measurements for p in participants)  # measurements still emitted
