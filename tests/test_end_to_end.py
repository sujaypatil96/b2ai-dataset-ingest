"""End-to-end: reader -> emitter -> canonical JSON, with round-trip + MetaData checks.

The multisession fixture always runs. The real-synthetic-data slice runs only when the
public synthetic tables have been fetched (``scripts/fetch_synthetic_data.sh``).
"""

from pathlib import Path

import phenopackets as pp
import pytest
from google.protobuf.json_format import Parse

from b2ai_dataset_ingest.emitters import PhenopacketEmitter
from b2ai_dataset_ingest.sources.voice import VoiceSource

CONFIG_DIR = Path(__file__).parents[1] / "config" / "voice"
SYNTHETIC = (
    Path(__file__).parents[1]
    / "data_synth"
    / "b2ai-voice-synthetic-phenotype"
    / "output"
    / "phenotype"
)


def _prefixes_used(pkt: pp.Phenopacket) -> set[str]:
    """Every CURIE prefix referenced by an OntologyClass in the packet."""
    used: set[str] = set()

    def note(ontology_class) -> None:
        if ontology_class and ontology_class.id:
            used.add(ontology_class.id.split(":", 1)[0])

    note(pkt.subject.taxonomy)
    for disease in pkt.diseases:
        note(disease.term)
        if disease.HasField("onset") and disease.onset.HasField("ontology_class"):
            note(disease.onset.ontology_class)
    for measurement in pkt.measurements:
        note(measurement.assay)
        if measurement.value.HasField("quantity"):
            note(measurement.value.quantity.unit)
        if measurement.HasField("time_observed") and measurement.time_observed.HasField(
            "ontology_class"
        ):
            note(measurement.time_observed.ontology_class)
    return {prefix for prefix in used if prefix}


def test_multisession_end_to_end_roundtrip(multisession_dir: Path, tmp_path: Path):
    participants = list(VoiceSource(root=multisession_dir, config_dir=CONFIG_DIR).read())
    written = PhenopacketEmitter().write_all(participants, tmp_path)
    assert written == 1

    out = tmp_path / "ms-0001.json"
    assert out.exists()

    # Round-trips through the canonical protobuf JSON parser.
    parsed = Parse(out.read_text(), pp.Phenopacket())
    assert parsed.subject.id == "ms-0001"

    # MetaData declares a Resource for every ontology prefix used.
    declared = {resource.namespace_prefix for resource in parsed.meta_data.resources}
    assert _prefixes_used(parsed) <= declared
    # Concretely: PHQ-9 (LOINC) + Parkinson (MONDO) + baseline/followup (NCIT) + taxon +
    # unit (UCUM) + VHI-10 custom item/total codes (b2ai).
    assert {"LOINC", "MONDO", "NCIT", "NCBITaxon", "UCUM", "b2ai"} <= declared

    # The precomputed VHI-10 total (vhi_10_calc_score=17) is emitted as a Measurement.
    totals = [m for m in parsed.measurements if m.assay.id == "b2ai:vhi10-total"]
    assert len(totals) == 1
    assert totals[0].value.quantity.value == 17.0


@pytest.mark.skipif(
    not SYNTHETIC.is_dir(),
    reason="synthetic data not fetched (run scripts/fetch_synthetic_data.sh)",
)
def test_real_synthetic_slice_roundtrips(tmp_path: Path):
    participants = list(VoiceSource(root=SYNTHETIC, config_dir=CONFIG_DIR).read())
    assert len(participants) > 100  # union across demographics/diagnosis/questionnaires

    written = PhenopacketEmitter().write_all(participants, tmp_path)
    assert written == len(participants)

    # Every emitted file parses and has complete MetaData resources.
    for path in sorted(tmp_path.glob("*.json")):
        parsed = Parse(path.read_text(), pp.Phenopacket())
        declared = {resource.namespace_prefix for resource in parsed.meta_data.resources}
        assert _prefixes_used(parsed) <= declared
