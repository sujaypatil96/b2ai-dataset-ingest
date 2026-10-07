"""Pydantic models for the canonical intermediate representation (IR).

These are deliberately a little more abstract than any single output target so that
emitters stay thin. They model *what was observed about a participant and when*, not
how a particular schema serializes it.

NOTE: this is the v1 IR. If we later want a documented, language-neutral schema, this
module is the natural thing to promote to a LinkML schema (see docs/adr/0001).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OntologyTerm(BaseModel):
    """A CURIE-identified ontology term, e.g. MONDO/HPO/LOINC/NCIT."""

    id: str = Field(..., description="CURIE, e.g. 'MONDO:0005180', 'HP:0001337'.")
    label: str | None = Field(None, description="Human-readable term label.")


class ReferenceRange(BaseModel):
    """The expected range for a measured value — the GA4GH ``ReferenceRange`` analogue.

    Emitted only when BOTH bounds are known. ``ReferenceRange.low``/``.high`` are plain
    proto3 doubles with no field presence, so an absent bound reads back as ``0.0`` and a
    one-sided range would serialize as "the normal range is 39 to 0". A source that supplies
    only one bound must drop the range, not half-fill it.
    """

    low: float
    high: float
    unit: OntologyTerm | None = Field(
        None, description="Defaults to the measurement's own unit at emit time."
    )


class Quantity(BaseModel):
    """A numeric measurement value with an optional unit."""

    value: float
    unit: OntologyTerm | None = None
    reference_range: ReferenceRange | None = Field(
        None, description="Per-row normal interval, where the source supplies both bounds."
    )


class TimePoint(BaseModel):
    """When an observation was made — the IR's analogue of a GA4GH ``TimeElement``.

    A source supplies whichever of these it has; the phenopacket emitter picks the
    richest representation available (timestamp > age > ontology_class > session label).
    Bridge2AI rows are keyed by ``session_id``, so that is always populated; the others
    are filled in as session->time metadata becomes available.
    """

    session_id: str = Field(..., description="Source session key, e.g. 'ses-baseline'.")
    timestamp: str | None = Field(None, description="ISO-8601 datetime, if known.")
    age_iso8601: str | None = Field(
        None, description="Age at observation as ISO-8601 duration, e.g. 'P63Y'."
    )
    ontology_class: OntologyTerm | None = Field(
        None, description="Ontology term for the timepoint/visit, if used."
    )


class Individual(BaseModel):
    """The subject of a phenopacket — sourced from the demographics table."""

    id: str = Field(..., description="Participant UUID from participant_id.")
    sex: str | None = Field(None, description="e.g. 'MALE'/'FEMALE'/'OTHER_SEX'/'UNKNOWN_SEX'.")
    gender: OntologyTerm | None = None
    age_iso8601: str | None = Field(
        None, description="Age at enrollment/last encounter as ISO-8601 duration."
    )
    taxonomy: OntologyTerm | None = Field(
        default=None, description="Defaults to Homo sapiens (NCBITaxon:9606) at emit time."
    )
    # IR-ONLY. The phenopacket schema has no race/ethnicity/ancestry field anywhere -- checked
    # 2026-10-06 against v2 individual.proto, phenopackets.proto and base.proto, and upstream
    # issue phenopacket-schema#231 ("Ethnicity") has been open since 2020. The emitter does
    # not write these; they are here for the run report and for a future target that has a
    # slot. Both are multi-select on the source form, hence lists.
    race: list[OntologyTerm] = Field(
        default_factory=list,
        description="Self-identified race, multi-select (NCIT). Not emitted to phenopackets.",
    )
    ethnicity: list[OntologyTerm] = Field(
        default_factory=list,
        description="Self-identified ethnicity, multi-select (NCIT). Not emitted to phenopackets.",
    )


class DiseaseObservation(BaseModel):
    """A diagnosis — sourced from a per-condition diagnosis table."""

    term: OntologyTerm = Field(..., description="MONDO term for the condition.")
    excluded: bool = Field(False, description="True if explicitly ruled out (e.g. controls).")
    onset: TimePoint | None = None


class ProcedureContext(BaseModel):
    """How an observation was produced — the GA4GH ``Procedure`` analogue.

    Its reason for existing is ``body_site``: a GA4GH ``Measurement`` has no laterality slot
    of its own, so a per-eye visual-acuity score can only say which eye via
    ``Measurement.procedure.body_site``. ``code`` is required because a Procedure carrying
    only a body site asserts an anatomical site with no act that touched it.
    """

    code: OntologyTerm = Field(..., description="The act performed, e.g. an NCIT assessment.")
    body_site: OntologyTerm | None = Field(
        None, description="Anatomical site, e.g. UBERON:0004549 right eye."
    )
    performed: TimePoint | None = None


class MeasurementObservation(BaseModel):
    """A quantitative or ordinal measurement — questionnaire scores and items."""

    assay: OntologyTerm = Field(..., description="What was measured (LOINC/NCIT/custom).")
    value_quantity: Quantity | None = None
    value_term: OntologyTerm | None = Field(
        None, description="For categorical/ordinal answers expressed as a term."
    )
    time: TimePoint | None = None
    description: str | None = Field(
        None,
        description=(
            "Disambiguates two observations sharing one assay — e.g. the first and second "
            "blood-pressure reading of a visit, which carry the same OMOP concept."
        ),
    )
    procedure: ProcedureContext | None = Field(
        None, description="Carries body_site/laterality; see ProcedureContext."
    )


class ExternalReference(BaseModel):
    """A pointer to an external record — the GA4GH ``ExternalReference`` analogue.

    Used as the source pointer on a self-report ``Evidence``: ``id`` is the source item CURIE
    (e.g. ``b2ai:phq9.feeling_depressed``), ``reference`` its full IRI.
    """

    id: str = Field(..., description="CURIE or identifier of the referenced record.")
    reference: str | None = Field(None, description="Full IRI/URL of the referenced record.")
    description: str | None = None


class Evidence(BaseModel):
    """Why an observation was asserted — the GA4GH ``Evidence`` analogue.

    ``evidence_code`` is an ECO term (e.g. ``ECO:0006160`` self-reported statement used in
    automatic assertion), so a questionnaire-derived phenotype is never weighted like a
    clinician-observed finding.
    """

    evidence_code: OntologyTerm = Field(..., description="ECO term for the kind of evidence.")
    reference: ExternalReference | None = None


class PhenotypicFeatureObservation(BaseModel):
    """A present/absent phenotype — symptom-level questionnaire items mapped to HPO."""

    type: OntologyTerm = Field(..., description="HPO term for the feature.")
    excluded: bool = Field(False, description="True if the feature is explicitly absent.")
    severity: OntologyTerm | None = None
    onset: TimePoint | None = None
    description: str | None = Field(
        None, description="Human-readable provenance (source item, predicate, when_value)."
    )
    evidence: list[Evidence] = Field(
        default_factory=list, description="Evidence codes/refs — e.g. an ECO self-report code."
    )


#: The GA4GH ``DrugType`` enum names (medical_action.proto). The IR carries the name rather than
#: the number so a source reader never imports the phenopackets package.
DRUG_TYPES = (
    "UNKNOWN_DRUG_TYPE",
    "PRESCRIPTION",
    "EHR_MEDICATION_LIST",
    "ADMINISTRATION_RELATED_TO_PROCEDURE",
)


class TreatmentObservation(BaseModel):
    """A medication the participant takes -- the GA4GH ``MedicalAction.treatment`` analogue.

    Modelled on a self-reported *current medications* list, so deliberately thin: an agent, how
    it is taken, and the dose and frequency as stated. ``dose`` and ``frequency`` are kept here
    but the phenopacket emitter does not write them: a ``DoseInterval`` also requires a
    timestamped ``interval``, which an undated medication list cannot honestly supply (and at
    age precision no date may leave the pipeline). The emitter writes agent, route and drug
    type and the run report counts the doses withheld. See docs/design/aireadi-ingest.md §8.
    """

    agent: OntologyTerm = Field(..., description="The drug, e.g. rxnorm:10582 levothyroxine.")
    route: OntologyTerm | None = Field(None, description="NCIT route of administration.")
    dose: Quantity | None = Field(None, description="Amount per administration, UCUM unit.")
    frequency: OntologyTerm | None = Field(
        None, description="NCIT schedule frequency, e.g. NCIT:C125004 Once Daily."
    )
    drug_type: Literal[
        "UNKNOWN_DRUG_TYPE",
        "PRESCRIPTION",
        "EHR_MEDICATION_LIST",
        "ADMINISTRATION_RELATED_TO_PROCEDURE",
    ] = Field(
        "UNKNOWN_DRUG_TYPE",
        description="The setting the record came from (GA4GH DrugType name); not its reliability.",
    )
    time: TimePoint | None = Field(
        None, description="When the list was taken, if known. Not emitted (no slot)."
    )
    description: str | None = None


class Participant(BaseModel):
    """One participant = the unit of one output phenopacket."""

    individual: Individual
    diseases: list[DiseaseObservation] = Field(default_factory=list)
    measurements: list[MeasurementObservation] = Field(default_factory=list)
    phenotypic_features: list[PhenotypicFeatureObservation] = Field(default_factory=list)
    treatments: list[TreatmentObservation] = Field(
        default_factory=list,
        description="Medications; each becomes a MedicalAction with a Treatment.",
    )
    source_dataset: str | None = Field(
        None, description="e.g. 'bridge2ai-voice' — recorded in output metadata."
    )
    audio_references: list[str] = Field(
        default_factory=list,
        description="External references to audio/derived features (referenced, not ingested).",
    )
    cohort: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Study-design attributes (arm, site, ML split). Recorded as provenance, never "
            "emitted as a Disease: AI-READI's study_group is a recruitment stratum and "
            "disagrees with the participant's own condition table."
        ),
    )
