"""Bridge2AI-Voice reader: phenotype TSVs -> canonical Participants.

The voice ``phenotype/`` tree is a set of TSVs keyed by ``participant_id`` +
``session_id``, each with a companion ReproSchema JSON data dictionary. In scope for v1:

    demographics/   -> Individual
    diagnosis/      -> DiseaseObservation (per-condition file basename -> MONDO)
    questionnaire/  -> MeasurementObservation (per-item ordinals + precomputed totals)

Audio/derived-feature tables (``task/``) are referenced, not ingested.

The synthetic data is messy in ways the reader must tolerate (all confirmed against the
public synthetic tables):

- rows are **not** unique per ``(participant_id, session_id)`` — a participant can have
  several rows for the same ``session_id``; these are merged "last non-empty wins";
- most ``session_id`` values are ``ses-baseline`` but a minority are raw UUIDs (generation
  noise) — each distinct ``session_id`` is treated as its own timepoint; and
- tables are wide and sparse — only mapped columns are read, missing ones are ignored.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import OrderedDict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from b2ai_dataset_ingest.mapping.engine import MappingEngine
from b2ai_dataset_ingest.mapping.loaders import is_placeholder, load_mapping, validate_mapping
from b2ai_dataset_ingest.model import (
    DiseaseObservation,
    Individual,
    MeasurementObservation,
    OntologyTerm,
    Participant,
    TimePoint,
)
from b2ai_dataset_ingest.sources.base import Source

logger = logging.getLogger(__name__)

# Recognized session labels -> the NCIT visit term used as the TimeElement fallback.
# (There are no real dates/ages in the data, so the session label is the richest signal.)
# Unrecognized session ids — e.g. stray UUIDs — leave the timepoint's ontology_class unset.
SESSION_TERMS: dict[str, OntologyTerm] = {
    "ses-baseline": OntologyTerm(id="NCIT:C25213", label="Baseline"),
    "ses-followup": OntologyTerm(id="NCIT:C16033", label="Follow-Up"),
}


class _Accumulator:
    """Collects the observations for one participant across all tables."""

    def __init__(self, participant_id: str) -> None:
        self.participant_id = participant_id
        self.individual: Individual | None = None
        self.diseases: list[DiseaseObservation] = []
        self.measurements: list[MeasurementObservation] = []
        self._disease_ids: set[str] = set()

    def add_disease(self, disease: DiseaseObservation) -> None:
        if disease.term.id not in self._disease_ids:
            self._disease_ids.add(disease.term.id)
            self.diseases.append(disease)


class VoiceSource(Source):
    dataset_id = "bridge2ai-voice"

    def read(self) -> Iterable[Participant]:
        participants: OrderedDict[str, _Accumulator] = OrderedDict()

        def accumulator(participant_id: str) -> _Accumulator:
            if participant_id not in participants:
                participants[participant_id] = _Accumulator(participant_id)
            return participants[participant_id]

        self._read_demographics(accumulator)
        self._read_diagnoses(accumulator)
        self._read_questionnaires(accumulator)

        for participant_id in sorted(participants):
            acc = participants[participant_id]
            individual = acc.individual or Individual(id=participant_id)
            yield Participant(
                individual=individual,
                diseases=acc.diseases,
                measurements=acc.measurements,
                source_dataset=self.dataset_id,
            )

    # -- demographics -> Individual --
    def _read_demographics(self, accumulator: Any) -> None:
        path = self.config_dir / "demographics.yaml"
        if not path.exists():
            return
        mapping = load_mapping(path)
        self._warn(mapping, "demographics.yaml")
        engine = MappingEngine(mapping)
        table = mapping.get("table", "demographics")
        rows = self._read_tsv(self.root / "demographics" / f"{table}.tsv")
        for participant_id, prows in _group_by(rows, _participant_key).items():
            merged = _merge_rows(prows)
            fields = engine.individual_fields(merged)
            accumulator(participant_id).individual = Individual(id=participant_id, **fields)

    # -- diagnosis -> Disease (one per resolved condition file the participant is in) --
    def _read_diagnoses(self, accumulator: Any) -> None:
        path = self.config_dir / "diagnosis.yaml"
        diag_dir = self.root / "diagnosis"
        if not path.exists() or not diag_dir.is_dir():
            return
        mapping = load_mapping(path)
        self._warn(mapping, "diagnosis.yaml")
        conditions = mapping.get("conditions") or {}
        for tsv in sorted(diag_dir.glob("*.tsv")):
            basename = tsv.stem
            term_spec = conditions.get(basename)
            # A resolved, non-control condition contributes a Disease. `control` and
            # unresolved (placeholder) conditions contribute the *participant* to the
            # universe but no Disease — so a participant whose only appearance is a control
            # or not-yet-coded diagnosis still gets an (id-only) phenopacket rather than
            # being silently dropped.
            if basename == "control":
                term = None
            elif term_spec is None or is_placeholder(term_spec):
                logger.info("diagnosis: %s has no resolved MONDO term; no Disease", basename)
                term = None
            else:
                term = OntologyTerm(**term_spec)
            rows = self._read_tsv(tsv)
            for participant_id, prows in _group_by(rows, _participant_key).items():
                acc = accumulator(participant_id)
                if term is not None:
                    onset = _timepoint(prows[0].get("session_id", ""))
                    acc.add_disease(DiseaseObservation(term=term, onset=onset))

    # -- questionnaires -> Measurements (per (participant, session) timepoint) --
    def _read_questionnaires(self, accumulator: Any) -> None:
        config_dir = self.config_dir / "questionnaire"
        if not config_dir.is_dir():
            return
        for cfg_path in sorted(config_dir.glob("*.yaml")):
            mapping = load_mapping(cfg_path)
            self._warn(mapping, f"questionnaire/{cfg_path.name}")
            engine = MappingEngine(mapping)
            table = mapping.get("table", cfg_path.stem)
            rows = self._read_tsv(self.root / "questionnaire" / f"{table}.tsv")
            if not rows:
                continue
            data_dict = self._read_data_elements(
                self.root / "questionnaire" / f"{table}.json"
            )
            for (participant_id, session_id), prows in _group_by(
                rows, _participant_session_key
            ).items():
                if len(prows) > 1:
                    logger.warning(
                        "questionnaire %s: %d rows for (%s, %s); merging last-non-empty-wins",
                        table,
                        len(prows),
                        participant_id,
                        session_id,
                    )
                merged = _merge_rows(prows)
                time = _timepoint(session_id)
                measurements = engine.measurements(merged, data_dict, time)
                accumulator(participant_id).measurements.extend(measurements)

    # -- IO helpers --
    @staticmethod
    def _read_tsv(path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh, delimiter="\t"))

    @staticmethod
    def _read_data_elements(path: Path) -> dict[str, Any]:
        """Return the ``data_elements`` map from a ReproSchema companion JSON, or ``{}``.

        The JSON is ``{<table>: {"data_elements": {<column>: {...}}}}``; we return the
        inner ``data_elements`` so the engine can read per-column ``choices`` directly.
        """
        if not path.exists():
            return {}
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("could not read data dict %s: %s", path, exc)
            return {}
        if not isinstance(doc, dict) or not doc:
            return {}
        top = next(iter(doc.values()))
        if isinstance(top, dict) and isinstance(top.get("data_elements"), dict):
            return top["data_elements"]
        return {}

    @staticmethod
    def _warn(mapping: dict[str, Any], source: str) -> None:
        for warning in validate_mapping(mapping):
            logger.warning("%s: %s", source, warning)


def _participant_key(row: dict[str, str]) -> str:
    return row.get("participant_id", "")


def _participant_session_key(row: dict[str, str]) -> tuple[str, str]:
    return row.get("participant_id", ""), row.get("session_id", "")


def _group_by(rows: Iterable[dict[str, str]], key: Any) -> OrderedDict[Any, list[dict]]:
    grouped: OrderedDict[Any, list[dict]] = OrderedDict()
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return grouped


def _merge_rows(rows: list[dict[str, str]]) -> dict[str, str]:
    """Collapse rows sharing a key into one, taking the last non-empty value per column."""
    if len(rows) == 1:
        return rows[0]
    merged: dict[str, str] = {}
    for row in rows:
        for column, value in row.items():
            if value and value.strip():
                merged[column] = value
    return merged


def _timepoint(session_id: str) -> TimePoint:
    """Build a TimePoint for a session id, attaching an NCIT term for known labels."""
    term = SESSION_TERMS.get(session_id)
    if term is None:
        logger.debug("unrecognized session id %r; leaving TimeElement unset", session_id)
    return TimePoint(session_id=session_id, ontology_class=term)
