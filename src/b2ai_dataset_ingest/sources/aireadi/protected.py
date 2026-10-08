"""The AI-READI protected supplement: REDCap exports -> Individual fields and Treatments.

AI-READI withholds sex, race/ethnicity, medications and 5-digit zip from its public releases
(docs.aireadi.org/docs/3/controlled-variables) and delivers them, under a separate DUA, as raw
REDCap exports keyed by the REDCap record id ``studyid`` -- the same 4-digit integer the OMOP
tables carry as ``person_id``. Two forms arrived in 2026-10, ahead of the matching OMOP tables
(dataset v3.0.0, Pilot through Wave 4):

    Demographics and Other   one row per participant     -> Individual.sex / .gender,
                                                             Individual.race / .ethnicity (IR only)
    Medications              one row per medication      -> TreatmentObservation
                             (repeating instrument)         (MedicalAction.treatment)

The configs under ``config/aireadi/protected/`` carry every mapping and every argument for it;
this module holds the four rules a config cannot express:

- **The supplement enriches; it never creates.** A row whose id matches no participant the
  clinical tables established is counted (``protected_rows_unmatched``) and dropped. A
  phenopacket carrying only a sex and a medication list would be a participant the clinical
  release does not contain, so the ingest runs the supplement last, once the universe is known.
- **The supplement wins on sex.** ``person.csv`` is redacted in every public release, so
  ``scrsex`` overwrites whatever ``person.yaml`` yielded. On a release that does carry sex the
  two should agree; a disagreement would be worth a validator check, not a silent precedence.
- **Free text is never read.** ``ancestry``, ``raceot``, ``cmname`` and every ``*ot`` "please
  specify" column are quasi-identifiers. The configs list them under ``dropped_columns`` and
  no code path here looks a free-text column up.
- **Choice codes are not CURIEs.** The dictionary spells NCIT concept codes as REDCap choice
  codes, and one is wrong (``C17459`` is NCIT *Hispanic or Latino*, not *American Indian or
  Alaska Native*). Every code is mapped explicitly to a verified term in config; nothing is
  minted from a column name.

Logging is PHI-safe on the reader's terms: table and column names and counts, never a cell
value or an id.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from typing import Any

from b2ai_dataset_ingest.mapping.engine import MappingEngine
from b2ai_dataset_ingest.mapping.loaders import is_placeholder
from b2ai_dataset_ingest.mapping.omop import AgeAnchor, as_number
from b2ai_dataset_ingest.mapping.redcap import checkbox_column, is_checked, normalize_id
from b2ai_dataset_ingest.model import (
    DRUG_TYPES,
    Individual,
    OntologyTerm,
    Quantity,
    TimePoint,
    TreatmentObservation,
)
from b2ai_dataset_ingest.reporting import IngestReport

logger = logging.getLogger(__name__)

#: ``person_id -> accumulator`` (anything with ``.individual`` and ``.treatments``), or None
#: when the clinical tables never established that participant.
Lookup = Callable[[str], Any]


# -- demographics ------------------------------------------------------------------
def apply_demographics(
    mapping: dict[str, Any],
    rows: Iterable[dict[str, str]],
    lookup: Lookup,
    report: IngestReport,
) -> None:
    """Set Individual fields from the wide demographics export, one row per participant.

    ``columns:`` goes through the existing :meth:`MappingEngine.individual_fields` path -- a
    ``value_map`` entry may recode onto an ``{id, label}`` term (gender identity) as well as
    onto an enum string, and ``null`` drops the field. ``checkbox_groups:`` are the REDCap
    multi-selects (race, ethnicity), each ticked choice contributing one term to a list field.
    """
    table = str(mapping.get("table", "protected_demographics"))
    id_column = str(mapping.get("id_column", "studyid"))
    refusals = {str(code) for code in (mapping.get("refusal_codes") or [])}
    columns: dict[str, dict[str, Any]] = mapping.get("columns") or {}
    groups: dict[str, dict[str, Any]] = mapping.get("checkbox_groups") or {}
    engine = MappingEngine(mapping)
    seen: set[str] = set()
    for row in rows:
        person_id = normalize_id(row.get(id_column))
        if not person_id:
            continue
        if person_id in seen:
            report.note_row_skipped(table, "duplicate id")
            continue
        seen.add(person_id)
        acc = lookup(person_id)
        if acc is None:
            report.protected_rows_unmatched[table] += 1
            continue
        for column in columns:
            if (row.get(column) or "").strip() in refusals:
                report.note_sentinel_answer(table, column)
        fields = engine.individual_fields(row, report=report)
        lists = _checkbox_terms(row, groups, table, refusals, report)
        if not fields and not any(lists.values()):
            continue
        base = acc.individual.model_dump() if acc.individual is not None else {"id": person_id}
        base.update(fields)
        base.update({name: terms for name, terms in lists.items() if terms})
        acc.individual = Individual(**base)
        for name in fields:
            report.protected_fields_set[name] += 1
        for name, terms in lists.items():
            if terms:
                report.protected_fields_set[name] += 1


def _checkbox_terms(
    row: dict[str, str],
    groups: dict[str, dict[str, Any]],
    table: str,
    refusals: set[str],
    report: IngestReport,
) -> dict[str, list[OntologyTerm]]:
    """``{Individual field: [terms]}`` for every checkbox group, from the ticked choices.

    A ticked choice mapped to ``null`` is a real answer with no term -- an *Other* whose free-text
    companion is never read -- and is counted as dropped by policy; a ticked refusal code is
    counted as a refusal. Column lookup is case-insensitive because REDCap lower-cases the
    choice code in the export and a hand-made CSV might not.
    """
    lowered = {key.lower(): key for key in row}
    result: dict[str, list[OntologyTerm]] = {}
    for group, spec in groups.items():
        target = str(spec.get("target", ""))
        field = target.split(".", 1)[1] if target.startswith("Individual.") else group
        terms: list[OntologyTerm] = []
        for code, term in (spec.get("choices") or {}).items():
            column = checkbox_column(group, code)
            key = column if column in row else lowered.get(column)
            if key is None or not is_checked(row.get(key)):
                continue
            if str(code) in refusals:
                report.note_sentinel_answer(table, column)
            elif term is None:
                report.note_item_dropped(table, column)
            elif is_placeholder(term):
                report.note_placeholder_skipped(table, column)
            else:
                terms.append(OntologyTerm(**term))
        result[field] = terms
    return result


# -- medications -------------------------------------------------------------------
def apply_medications(
    mapping: dict[str, Any],
    rows: Iterable[dict[str, str]],
    lookup: Lookup,
    anchors: dict[str, AgeAnchor],
    report: IngestReport,
) -> None:
    """One medication row -> one :class:`TreatmentObservation` on its participant.

    The agent is required and comes from the RxNorm code column; a row with no code, or with a
    code that is not a bare RXCUI, emits nothing and is counted. Route, dose and frequency are
    each optional and drop independently, so a dose Excel mangled into a date costs the dose
    and not the medication. Dose and frequency land in the IR and are counted as *withheld*,
    because the phenopacket emitter does not write them -- see the emitter and the config
    header for why.
    """
    table = str(mapping.get("table", "protected_medications"))
    id_column = str(mapping.get("id_column", "studyid"))
    instrument_column = mapping.get("instrument_column")
    instrument = mapping.get("instrument")
    instance_column = mapping.get("instance_column")
    agent_spec: dict[str, Any] = mapping.get("agent") or {}
    code_column = str(agent_spec.get("code_column", "rxnorm_code"))
    label_column = str(agent_spec.get("label_column", "rxnorm_term"))
    prefix = str(agent_spec.get("prefix", "rxnorm"))
    pattern = re.compile(str(agent_spec.get("pattern", r"^[0-9]{1,7}$")))
    drug_type = _drug_type(mapping, table)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        person_id = normalize_id(row.get(id_column))
        if not person_id:
            continue
        if instrument_column and instrument:
            found = (row.get(str(instrument_column)) or "").strip()
            if found and found != instrument:
                report.note_row_skipped(table, "other instrument")
                continue
        if instance_column:
            key = (person_id, normalize_id(row.get(str(instance_column))))
            if key in seen:
                report.note_row_skipped(table, "duplicate instance")
                continue
            seen.add(key)
        acc = lookup(person_id)
        if acc is None:
            report.protected_rows_unmatched[table] += 1
            continue
        code = normalize_id(row.get(code_column))
        if not code:
            report.agents_missing[f"{table}.{code_column}"] += 1
            continue
        if not pattern.match(code):
            report.agents_malformed[f"{table}.{code_column}"] += 1
            continue
        label = (row.get(label_column) or "").strip() or None
        route = _coded_term(row, mapping.get("route"), table, report)
        frequency = _coded_term(row, mapping.get("frequency"), table, report)
        dose = _dose(row, mapping.get("dose"), table, report)
        anchor = anchors.get(person_id)
        acc.treatments.append(
            TreatmentObservation(
                agent=OntologyTerm(id=f"{prefix}:{code}", label=label),
                route=route,
                dose=dose,
                frequency=frequency,
                drug_type=drug_type,
                time=TimePoint(session_id="enrollment", age_iso8601=anchor.iso)
                if anchor is not None
                else None,
            )
        )
        report.treatments_emitted += 1
        if dose is not None or frequency is not None:
            report.doses_withheld += 1


def _drug_type(mapping: dict[str, Any], table: str) -> str:
    declared = str(mapping.get("drug_type") or "UNKNOWN_DRUG_TYPE")
    if declared in DRUG_TYPES:
        return declared
    logger.warning(
        "%s: drug_type %r is not a DrugType name; using UNKNOWN_DRUG_TYPE", table, declared
    )
    return "UNKNOWN_DRUG_TYPE"


def _match_key(raw: str, terms: dict[Any, Any]) -> Any | None:
    """The config key a cell names, tolerating Excel's int/str drift and case."""
    if raw in terms:
        return raw
    normalized = normalize_id(raw)
    if normalized in terms:
        return normalized
    lowered = {str(key).lower(): key for key in terms}
    return lowered.get(raw.lower(), lowered.get(normalized.lower()))


def _coded_term(
    row: dict[str, str],
    spec: dict[str, Any] | None,
    table: str,
    report: IngestReport,
) -> OntologyTerm | None:
    """A picklist cell -> its configured term; None when blank, *Other*, or unknown."""
    if not spec:
        return None
    column = str(spec.get("column", ""))
    raw = (row.get(column) or "").strip()
    if not raw:
        return None
    terms: dict[Any, Any] = spec.get("terms") or {}
    key = _match_key(raw, terms)
    if key is None:
        # PHI-safe: the column, never the cell.
        logger.warning("%s: no term configured for a value in column %s; dropping", table, column)
        report.note_value_map_miss(table, column)
        return None
    term = terms[key]
    if term is None:
        report.note_item_dropped(table, column)
        return None
    if is_placeholder(term):
        report.note_placeholder_skipped(table, column)
        return None
    return OntologyTerm(**term)


def _dose(
    row: dict[str, str],
    spec: dict[str, Any] | None,
    table: str,
    report: IngestReport,
) -> Quantity | None:
    """Amount + unit -> Quantity; None, counted, when either half is unusable.

    ``cmdos`` is free text ("Amount taken"), so it may hold ``1-2`` -- or, after Excel, the
    date that text was auto-converted into. Neither parses as a number and both are counted
    under ``doses_unparsed``. A numeric amount with an *Other* or unknown unit is dropped too:
    ``Quantity.unit`` is required and a bare number is not a dose.
    """
    if not spec:
        return None
    value_column = str(spec.get("value_column", ""))
    unit_column = str(spec.get("unit_column", ""))
    raw = (row.get(value_column) or "").strip()
    if not raw:
        return None
    value = as_number(raw)
    if value is None:
        report.doses_unparsed[f"{table}.{value_column}"] += 1
        return None
    units: dict[Any, Any] = spec.get("units") or {}
    unit_raw = (row.get(unit_column) or "").strip()
    key = _match_key(unit_raw, units) if unit_raw else None
    term = units.get(key) if key is not None else None
    if term is None or is_placeholder(term):
        report.dose_units_unmapped[f"{table}.{unit_column}"] += 1
        return None
    return Quantity(value=value, unit=OntologyTerm(**term))


__all__ = ["apply_demographics", "apply_medications"]
