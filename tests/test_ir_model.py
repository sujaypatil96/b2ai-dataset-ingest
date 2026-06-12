"""The canonical IR is implemented now (data classes), so these tests pass today."""

from b2ai_dataset_ingest.model import (
    DiseaseObservation,
    Individual,
    MeasurementObservation,
    OntologyTerm,
    Participant,
    PhenotypicFeatureObservation,
    Quantity,
    TimePoint,
)


def test_minimal_participant():
    p = Participant(individual=Individual(id="ms-0001"))
    assert p.individual.id == "ms-0001"
    assert p.diseases == []
    assert p.measurements == []
    assert p.phenotypic_features == []


def test_participant_with_observations():
    baseline = TimePoint(session_id="ses-baseline")
    followup = TimePoint(session_id="ses-followup")
    p = Participant(
        individual=Individual(id="ms-0001", sex="MALE", age_iso8601="P63Y"),
        source_dataset="bridge2ai-voice",
        diseases=[
            DiseaseObservation(
                term=OntologyTerm(id="MONDO:0005180", label="Parkinson disease"),
                onset=baseline,
            )
        ],
        measurements=[
            MeasurementObservation(
                assay=OntologyTerm(id="LOINC:44261-6", label="PHQ-9 total score"),
                value_quantity=Quantity(value=4.0),
                time=baseline,
            ),
            MeasurementObservation(
                assay=OntologyTerm(id="LOINC:44261-6", label="PHQ-9 total score"),
                value_quantity=Quantity(value=12.0),
                time=followup,
            ),
        ],
        phenotypic_features=[
            PhenotypicFeatureObservation(
                type=OntologyTerm(id="HP:0000716", label="Depression"), onset=followup
            )
        ],
    )
    # Same measure across two sessions = time course.
    sessions = [m.time.session_id for m in p.measurements]
    assert sessions == ["ses-baseline", "ses-followup"]
    assert p.diseases[0].excluded is False
