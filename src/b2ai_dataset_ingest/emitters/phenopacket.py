"""IR -> GA4GH Phenopacket emitter (STUB) — the first and committed output target.

Mapping intent (implemented in the next task):

    Individual                     -> Phenopacket.subject (Individual)
    DiseaseObservation             -> Phenopacket.diseases (Disease, MONDO term)
    MeasurementObservation         -> Phenopacket.measurements (Measurement, time_observed)
    PhenotypicFeatureObservation   -> Phenopacket.phenotypic_features (PhenotypicFeature, onset)
    TimePoint                      -> TimeElement (timestamp | age | ontologyClass)

Built on the official GA4GH ``phenopackets`` package (protobuf, schema v2). Serialization
to JSON uses ``google.protobuf.json_format.MessageToJson``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from b2ai_dataset_ingest.emitters.base import Emitter
from b2ai_dataset_ingest.model import Participant


class PhenopacketEmitter(Emitter):
    target_id = "phenopacket"

    def emit(self, participant: Participant) -> object:
        # TODO(next task): build a phenopackets.schema.v2.Phenopacket from the IR.
        raise NotImplementedError("PhenopacketEmitter.emit is not implemented yet")

    def write_all(self, participants: Iterable[Participant], out_dir: Path) -> int:
        # TODO(next task): emit() each participant and write one JSON phenopacket per file.
        raise NotImplementedError("PhenopacketEmitter.write_all is not implemented yet")
