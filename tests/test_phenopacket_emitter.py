"""Phenopacket emitter: IR Participant -> schema-v2 Phenopacket."""

import phenopackets as pp

from b2ai_dataset_ingest.emitters import PhenopacketEmitter
from b2ai_dataset_ingest.model import (
    DiseaseObservation,
    Evidence,
    ExternalReference,
    Individual,
    MeasurementObservation,
    OntologyTerm,
    Participant,
    PhenotypicFeatureObservation,
    Quantity,
    TimePoint,
)


def test_emit_single_participant():
    pkt = PhenopacketEmitter().emit(Participant(individual=Individual(id="ms-0001")))
    assert isinstance(pkt, pp.Phenopacket)
    assert pkt.subject.id == "ms-0001"
    # Taxonomy defaults to Homo sapiens, with a matching MetaData resource.
    assert pkt.subject.taxonomy.id == "NCBITaxon:9606"
    prefixes = {r.namespace_prefix for r in pkt.meta_data.resources}
    assert "NCBITaxon" in prefixes


def test_emit_disease_and_measurement_with_time():
    baseline = TimePoint(
        session_id="ses-baseline",
        ontology_class=OntologyTerm(id="NCIT:C25213", label="Baseline"),
    )
    participant = Participant(
        individual=Individual(id="p1", sex="FEMALE", age_iso8601="P40Y"),
        diseases=[
            DiseaseObservation(
                term=OntologyTerm(id="MONDO:0005180", label="Parkinson disease"),
                onset=baseline,
            )
        ],
        measurements=[
            MeasurementObservation(
                assay=OntologyTerm(id="LOINC:44255-8", label="depressed mood"),
                value_quantity=Quantity(
                    value=2.0, unit=OntologyTerm(id="UCUM:{score}", label="score")
                ),
                time=baseline,
            )
        ],
    )
    pkt = PhenopacketEmitter().emit(participant)

    assert pkt.subject.sex == pp.FEMALE
    assert pkt.subject.time_at_last_encounter.age.iso8601duration == "P40Y"

    [disease] = pkt.diseases
    assert disease.term.id == "MONDO:0005180"
    assert disease.onset.ontology_class.id == "NCIT:C25213"

    [measurement] = pkt.measurements
    assert measurement.assay.id == "LOINC:44255-8"
    assert measurement.value.quantity.value == 2.0
    assert measurement.value.quantity.unit.id == "UCUM:{score}"
    assert measurement.time_observed.ontology_class.id == "NCIT:C25213"

    # Every prefix used has a MetaData resource.
    prefixes = {r.namespace_prefix for r in pkt.meta_data.resources}
    assert {"MONDO", "LOINC", "NCIT", "UCUM", "NCBITaxon"} <= prefixes


def test_emit_phenotypic_feature_and_hp_resource():
    participant = Participant(
        individual=Individual(id="p3"),
        phenotypic_features=[
            PhenotypicFeatureObservation(
                type=OntologyTerm(id="HP:0001337", label="Tremor"), excluded=False
            )
        ],
    )
    pkt = PhenopacketEmitter().emit(participant)
    [feature] = pkt.phenotypic_features
    assert feature.type.id == "HP:0001337"
    prefixes = {r.namespace_prefix for r in pkt.meta_data.resources}
    assert "HP" in prefixes


def test_derived_feature_renders_provenance_and_declares_resources():
    # A self-report-derived feature (ADR-0003): excluded pole + ECO Evidence +
    # an ExternalReference to the b2ai source item; both new prefixes must get a Resource.
    participant = Participant(
        individual=Individual(id="p5"),
        phenotypic_features=[
            PhenotypicFeatureObservation(
                type=OntologyTerm(id="HP:0000716", label="Depression"),
                excluded=True,
                description="Derived absent from self-reported item b2ai:phq9.feeling_depressed",
                evidence=[
                    Evidence(
                        evidence_code=OntologyTerm(id="ECO:0006160", label="self-reported"),
                        reference=ExternalReference(
                            id="b2ai:phq9.feeling_depressed",
                            reference="https://example.org/phq9.feeling_depressed",
                            description="Feeling down, depressed, or hopeless",
                        ),
                    )
                ],
            )
        ],
    )
    pkt = PhenopacketEmitter().emit(participant)
    [feature] = pkt.phenotypic_features
    assert feature.excluded is True
    assert feature.description.startswith("Derived absent")
    [evidence] = feature.evidence
    assert evidence.evidence_code.id == "ECO:0006160"
    assert evidence.reference.id == "b2ai:phq9.feeling_depressed"
    assert evidence.reference.description == "Feeling down, depressed, or hopeless"
    # The ECO code and the b2ai ExternalReference id both contribute a MetaData Resource.
    prefixes = {r.namespace_prefix for r in pkt.meta_data.resources}
    assert {"HP", "ECO", "b2ai", "NCBITaxon"} <= prefixes


def test_metadata_excludes_shadowed_value_term_prefix():
    # value_term is shadowed by value_quantity (the emitter emits the quantity), so the
    # value_term's prefix (NCIT) must NOT appear as a MetaData resource.
    participant = Participant(
        individual=Individual(id="p4"),
        measurements=[
            MeasurementObservation(
                assay=OntologyTerm(id="LOINC:44255-8", label="x"),
                value_quantity=Quantity(
                    value=1.0, unit=OntologyTerm(id="UCUM:{score}", label="score")
                ),
                value_term=OntologyTerm(id="NCIT:C25626", label="Present"),
            )
        ],
    )
    pkt = PhenopacketEmitter().emit(participant)
    [measurement] = pkt.measurements
    assert measurement.value.HasField("quantity")
    prefixes = {r.namespace_prefix for r in pkt.meta_data.resources}
    assert "NCIT" not in prefixes
    assert {"LOINC", "UCUM", "NCBITaxon"} <= prefixes


def test_uuid_session_leaves_time_unset():
    # A stray UUID session has no recognized term -> no TimeElement fabricated.
    participant = Participant(
        individual=Individual(id="p2"),
        measurements=[
            MeasurementObservation(
                assay=OntologyTerm(id="LOINC:44255-8", label="depressed mood"),
                value_quantity=Quantity(
                    value=1.0, unit=OntologyTerm(id="UCUM:{score}", label="score")
                ),
                time=TimePoint(session_id="5E054A0F-CFA2-46AF-9248-14949EAB163E"),
            )
        ],
    )
    pkt = PhenopacketEmitter().emit(participant)
    [measurement] = pkt.measurements
    assert not measurement.HasField("time_observed")
