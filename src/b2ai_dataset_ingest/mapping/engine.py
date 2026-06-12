"""Apply YAML mapping configs to source rows to produce IR fragments (STUB).

The engine is the reusable core shared across datasets: given a table's rows and its
mapping config, it emits IR objects (Individual fields, DiseaseObservation,
MeasurementObservation, PhenotypicFeatureObservation). Source readers compose these
fragments into Participants.

Implementation is deferred to the next task.
"""

from __future__ import annotations

from typing import Any


class MappingEngine:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self.mapping = mapping

    def apply(self, row: dict[str, Any]) -> Any:
        # TODO(next task): translate one source row into IR fragments per the mapping.
        raise NotImplementedError("MappingEngine.apply is not implemented yet")
