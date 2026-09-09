"""OMOP CDM long-table primitives — the EAV counterpart to :mod:`mapping.engine`.

The Voice mapping engine reads *wide* rows: a column name is the item key and the cell is
the answer. OMOP CDM is *long*: a row is one observation, the item is named by
``<domain>_source_value``, and the value sits in ``value_as_number`` / ``value_as_string``.
This module holds the primitives that bridge the two, plus the OMOP-specific value rules
that the Voice engine has no notion of (units, reference ranges, censoring operators).

Nothing here is AI-READI-specific — OMOP CDM is a published standard, so a second OMOP
dataset reuses this file and writes only its own config.

Four rules encoded here are load-bearing, and each was established against real data:

- **The item key is the REDCap variable, never ``*_concept_id``.** A concept id is the
  *assay* code and is not unique per item: OMOP ``3004249`` backs both ``bp1_sysbp_vsorres``
  and ``bp2_sysbp_vsorres``, and ``4047085`` backs all twenty monofilament sites. The
  variable — the text before the first comma of the source value — is unique.
- **``*_source_value`` is hard-truncated at 49 characters**, so its label half is a hint for
  a curator and never a label source. :func:`item_key` reads only the variable half.
- **Timestamps must be RFC3339 with a ``Z``.** ``TimeElement.timestamp.FromJsonString``
  rejects ``"2023-12-12"``, ``"2023-12-12 08:19:00"`` and ``"2023-12-12T08:19:00"`` alike,
  and the emitter *catches* that ValueError and silently falls back — so an un-normalized
  OMOP datetime loses every ``time_observed`` without failing. :func:`to_rfc3339` normalizes
  before a value ever reaches a :class:`~b2ai_dataset_ingest.model.core.TimePoint`.
- **Blank and zero are different, and which is which depends on the column.** ``"0"`` means
  "no matching concept" in a ``*_concept_id`` column but is a *valid answer* in
  ``value_as_number``, where it is an ordinary — often the modal — answer. Hence two
  separate null sets: :data:`NULL_VALUES` and :data:`NULL_CONCEPT_IDS`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Blank spellings in a *value* column. ``"0"`` is deliberately absent — it is an answer.
NULL_VALUES = ("", " ", "N/A")

#: Blank spellings in a ``*_concept_id`` column, where ``0`` is OMOP's "no matching concept".
NULL_CONCEPT_IDS = ("", " ", "0", "0.0")

#: REDCap refusal / don't-know / not-applicable codes seen in ``value_as_number``.
#: A cut-point over a scale carrying these must be written ``== n``, never ``>= n``.
SENTINEL_ANSWERS = frozenset({"555", "777", "888", "999", "555.0", "777.0", "888.0", "999.0"})

#: OMOP ``operator_concept_id`` values that mark a *bounded* (censored) result, e.g. a
#: below-detection-limit assay. GA4GH ``Quantity`` has no operator slot, so a bounded row
#: must be dropped rather than reported as a measured value.
#:
#: Note the polarity: the operator column is very often ``0`` ("not recorded") rather than
#: ``4172703`` ("="). In the VUMC synthetic release it is ``0`` on 178,806 of 767,814 rows —
#: every vital and every CBC item — so gating on "must equal 4172703" would delete them
#: all. Only an explicit bound disqualifies a value.
BOUNDING_OPERATORS = frozenset({"4171756"})

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATETIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.\d+)?Z?$")


def item_key(source_value: str) -> str:
    """The REDCap variable naming one OMOP item.

    ``"import_hba1c, Hemoglobin A1c/Hemoglobin.total in "`` -> ``"import_hba1c"``. A source
    value with no comma is itself the key (30 measurement and 4 observation items have none,
    e.g. ``"naming"``, ``"digitspan"``). Returns ``""`` for a blank cell.
    """
    return (source_value or "").split(",", 1)[0].strip()


def to_rfc3339(value: str) -> str | None:
    """Normalize an OMOP date/datetime to the only form protobuf accepts, or None.

    ``"2023-12-12 08:19:00"`` -> ``"2023-12-12T08:19:00Z"``; ``"2023-12-12"`` ->
    ``"2023-12-12T00:00:00Z"``. Anything unrecognized returns None so the caller leaves the
    TimeElement unset rather than emitting a value the emitter would silently discard.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    match = _DATETIME_RE.match(raw)
    if match:
        return f"{match.group(1)}T{match.group(2)}Z"
    match = _DATE_RE.match(raw)
    if match:
        return f"{raw}T00:00:00Z"
    # PHI-safe: a date is a HIPAA identifier, so report the shape, never the value.
    logger.debug("unparseable OMOP timestamp (%d chars); leaving time unset", len(raw))
    return None


def is_blank(value: Any, nulls: Iterable[str] = NULL_VALUES) -> bool:
    """True if a cell is one of the blank spellings for its column kind."""
    return str(value if value is not None else "").strip() in {n.strip() for n in nulls}


def is_sentinel(value: Any) -> bool:
    """True if a numeric answer is a REDCap refusal / don't-know code (555/777/888/999)."""
    return str(value if value is not None else "").strip() in SENTINEL_ANSWERS


def is_bounded(operator_concept_id: Any) -> bool:
    """True if the row's operator marks a censored (``<`` / ``>``) rather than point value."""
    return str(operator_concept_id if operator_concept_id is not None else "").strip() in (
        BOUNDING_OPERATORS
    )


def as_number(value: Any) -> float | None:
    """Parse a numeric cell; None when blank or non-numeric. ``0`` parses to ``0.0``."""
    raw = str(value if value is not None else "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class LongCell:
    """One OMOP long row, reduced to what a mapping needs.

    Flattening straight to ``dict[str, str]`` would make ``operator``, ``unit_source``,
    ``range_low/high`` and ``qualifier`` structurally invisible, which is how a pivot
    quietly turns a censored result into a measured one. The pivot therefore yields
    ``dict[str, LongCell]``, and :meth:`as_row` projects the plain wide view for the
    dataset-agnostic consumers (``hpo_rules.derive_features``) that only want the answer.
    """

    item: str
    value: str = ""
    date: str = ""
    unit_source: str = ""
    range_low: str = ""
    range_high: str = ""
    operator: str = ""
    qualifier: str = ""
    visit_id: str = ""

    @property
    def censored(self) -> bool:
        return is_bounded(self.operator)

    @property
    def sentinel(self) -> bool:
        return is_sentinel(self.value)


def as_row(cells: dict[str, LongCell]) -> dict[str, str]:
    """Project a pivoted group to the plain ``{item: value}`` view.

    This is what makes ``mapping.hpo_rules.derive_features`` — which is already fully
    dataset-agnostic — run over OMOP rows with no change at all.
    """
    return {item: cell.value for item, cell in cells.items()}


class OmopTableSpec:
    """The column names one OMOP domain table uses, read from its YAML config."""

    def __init__(self, mapping: dict[str, Any]) -> None:
        self.mapping = mapping
        self.table: str = mapping.get("table", "?")
        self.id_column: str = mapping.get("id_column", "person_id")
        self.key_column: str = mapping.get("key_column", f"{self.table}_source_value")
        self.date_column: str = mapping.get("date_column", f"{self.table}_date")
        self.visit_column: str = mapping.get("visit_column", "visit_occurrence_id")
        self.value_columns: list[str] = list(
            mapping.get("value_columns") or ["value_as_number", "value_as_string"]
        )

    def cell(self, row: dict[str, str]) -> LongCell | None:
        """Build a :class:`LongCell` from one raw CSV row, or None if it names no item."""
        key = item_key(row.get(self.key_column, ""))
        if not key:
            return None
        value = ""
        for column in self.value_columns:
            candidate = (row.get(column) or "").strip()
            if not is_blank(candidate):
                value = candidate
                break
        return LongCell(
            item=key,
            value=value,
            date=(row.get(self.date_column) or "").strip(),
            unit_source=(row.get("unit_source_value") or "").strip(),
            range_low=(row.get("range_low") or "").strip(),
            range_high=(row.get("range_high") or "").strip(),
            operator=(row.get("operator_concept_id") or "").strip(),
            qualifier=(row.get("qualifier_concept_id") or "").strip(),
            visit_id=(row.get(self.visit_column) or "").strip(),
        )


def pivot(
    rows: Iterable[dict[str, str]], spec: OmopTableSpec
) -> Iterator[tuple[str, dict[str, LongCell]]]:
    """Group long rows into ``(person_id, {item: LongCell})``.

    Streams: rows for one participant are assumed contiguous only in the sense that the
    caller may hand this a whole table; the grouping itself buffers one dict per participant,
    which is bounded by the item count (~110), not by the row count.

    Collisions — the same ``(person, item)`` twice — keep the *first* cell and are reported
    by the caller via the returned duplicate count on each group. Verified against the real
    release: 0 collisions in ``measurement.csv`` and ``procedure_occurrence.csv``.
    """
    grouped: dict[str, dict[str, LongCell]] = {}
    for row in rows:
        cell = spec.cell(row)
        if cell is None:
            continue
        person = (row.get(spec.id_column) or "").strip()
        if not person:
            continue
        grouped.setdefault(person, {}).setdefault(cell.item, cell)
    yield from grouped.items()
