"""Apply a YAML mapping config to source rows to produce IR fragments.

The engine is the reusable core shared across datasets: given a table's mapping config it
turns one source row into IR objects. Two table shapes are supported in v1:

- **Demographics** (``produces: Individual`` with a ``columns`` block) -> a dict of
  :class:`~b2ai_dataset_ingest.model.core.Individual` field values, via
  :meth:`MappingEngine.individual_fields`.
- **Questionnaire** (``items`` and/or ``score``) -> a list of
  :class:`~b2ai_dataset_ingest.model.core.MeasurementObservation`, via
  :meth:`MappingEngine.measurements`.

Ordinal answers become ``Quantity(value=<int>, unit=UCUM {score})`` (per the confirmed
plan). The integer for an answer string is read from the companion ReproSchema data dict's
per-item ``choices`` when available, falling back to the config's ``ordinal_scale`` (used
by test fixtures that ship no data dict). Diagnosis is basename-driven and handled by the
reader, not here.
"""

from __future__ import annotations

import logging
from typing import Any

from b2ai_dataset_ingest.model import (
    MeasurementObservation,
    OntologyTerm,
    Quantity,
    TimePoint,
)

logger = logging.getLogger(__name__)

#: UCUM unit for unitless questionnaire scores. ``Quantity.unit`` is REQUIRED by the
#: phenopacket schema, so every numeric measurement carries this even when "unitless".
SCORE_UNIT = OntologyTerm(id="UCUM:{score}", label="score")


class MappingEngine:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self.mapping = mapping

    # -- generic entry point (used by tests / callers that don't know the table shape) --
    def apply(
        self, row: dict[str, Any], data_dict: dict[str, Any] | None = None
    ) -> list[Any]:
        """Translate one row into IR fragments, dispatching on the mapping's shape."""
        if "items" in self.mapping or "score" in self.mapping:
            return self.measurements(row, data_dict)
        if self.mapping.get("produces") == "Individual" or "columns" in self.mapping:
            return [self.individual_fields(row)]
        return []

    # -- demographics -> Individual field values --
    def individual_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        """Return Individual field values (e.g. ``sex``, ``age_iso8601``) for one row.

        ``Individual.id`` is set by the reader from ``participant_id``, not here. Columns
        whose value is blank, or that recode/transform to nothing, are omitted.
        """
        fields: dict[str, Any] = {}
        for column, spec in (self.mapping.get("columns") or {}).items():
            raw = (row.get(column) or "").strip()
            if not raw:
                continue
            target = spec.get("target", "")
            if not target.startswith("Individual."):
                continue
            field = target.split(".", 1)[1]
            value = self._recode(raw, spec)
            if value is not None:
                fields[field] = value
        return fields

    def _recode(self, raw: str, spec: dict[str, Any]) -> Any:
        """Apply a column spec's ``value_map`` then ``transform`` to a raw cell value."""
        value: Any = raw
        value_map = spec.get("value_map")
        if value_map:
            if raw in value_map:
                value = value_map[raw]
            else:
                # tolerate case / code-vs-label differences from the source vocabulary
                lowered = {str(k).lower(): v for k, v in value_map.items()}
                if raw.lower() in lowered:
                    value = lowered[raw.lower()]
                else:
                    logger.warning("no value_map entry for %r; dropping", raw)
                    return None
        transform = spec.get("transform")
        if transform:
            value = self._transform(transform, value)
        return value

    @staticmethod
    def _transform(name: str, value: Any) -> Any:
        if name == "years_to_iso8601":
            return MappingEngine.years_to_iso8601(value)
        logger.warning("unknown transform %r; passing value through", name)
        return value

    @staticmethod
    def years_to_iso8601(value: Any) -> str | None:
        """``"63"`` / ``"54.0"`` -> ``"P63Y"`` / ``"P54Y"``; None if not a number."""
        try:
            years = int(float(str(value).strip()))
        except (TypeError, ValueError):
            logger.warning("age %r is not numeric; leaving age unset", value)
            return None
        return f"P{years}Y"

    # -- questionnaire -> Measurements --
    def measurements(
        self,
        row: dict[str, Any],
        data_dict: dict[str, Any] | None = None,
        time: TimePoint | None = None,
    ) -> list[MeasurementObservation]:
        """Return per-item ordinal Measurements plus a precomputed total, if configured."""
        out: list[MeasurementObservation] = []

        for column, assay in (self.mapping.get("items") or {}).items():
            raw = (row.get(column) or "").strip()
            if not raw:
                continue
            ordinal = self._ordinal_value(column, raw, data_dict)
            if ordinal is None:
                logger.warning(
                    "questionnaire %s: no ordinal value for %s=%r; skipping item",
                    self.mapping.get("table", "?"),
                    column,
                    raw,
                )
                continue
            out.append(
                MeasurementObservation(
                    assay=OntologyTerm(**assay),
                    value_quantity=Quantity(value=float(ordinal), unit=SCORE_UNIT),
                    time=time,
                )
            )

        score = self.mapping.get("score")
        if isinstance(score, dict):
            column = score.get("source_column")
            raw = (row.get(column) or "").strip() if column else ""
            if raw:
                total = self._as_number(raw)
                if total is not None:
                    unit = OntologyTerm(**score["unit"]) if score.get("unit") else SCORE_UNIT
                    out.append(
                        MeasurementObservation(
                            assay=OntologyTerm(**score["assay"]),
                            value_quantity=Quantity(value=total, unit=unit),
                            time=time,
                        )
                    )
                else:
                    logger.warning(
                        "questionnaire %s: total %r in %s is not numeric; skipping",
                        self.mapping.get("table", "?"),
                        raw,
                        column,
                    )
        return out

    def _ordinal_value(
        self, column: str, answer: str, data_dict: dict[str, Any] | None
    ) -> int | None:
        """Map an answer string to its ordinal integer.

        Prefers the per-item ``choices`` from the companion data dict (which handles items
        on a non-default scale for free); falls back to the config ``ordinal_scale``.
        """
        choice_map = self._choices_map(column, data_dict)
        if choice_map and answer in choice_map:
            return choice_map[answer]
        fallback = self.mapping.get("ordinal_scale") or {}
        if answer in fallback:
            return fallback[answer]
        return None

    @staticmethod
    def _choices_map(
        column: str, data_dict: dict[str, Any] | None
    ) -> dict[str, int] | None:
        """Build ``answer-text -> value`` from a data-dict element's ``choices``."""
        element = (data_dict or {}).get(column)
        if not isinstance(element, dict):
            return None
        choices = element.get("choices")
        if not choices:
            return None
        mapping: dict[str, int] = {}
        for choice in choices:
            name = choice.get("name")
            if isinstance(name, dict):
                name = name.get("en")
            value = choice.get("value")
            if name is not None and isinstance(value, int):
                mapping[name] = value
        return mapping or None

    @staticmethod
    def _as_number(raw: str) -> float | None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
