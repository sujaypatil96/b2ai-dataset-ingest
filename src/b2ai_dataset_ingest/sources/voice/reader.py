"""Bridge2AI-Voice reader (STUB).

The voice ``phenotype/`` tree is a set of TSVs keyed by ``participant_id`` +
``session_id``, with companion ReproSchema JSON data dictionaries. In scope for v1:

    demographics/   -> Individual
    diagnosis/      -> DiseaseObservation (per-condition file basename -> MONDO)
    questionnaire/  -> MeasurementObservation (scores) + PhenotypicFeatureObservation (HPO)

Audio/derived-feature tables (task/) are referenced, not ingested.

Implementation is deferred to the next task; this stub fixes the interface only.
"""

from __future__ import annotations

from collections.abc import Iterable

from b2ai_dataset_ingest.model import Participant
from b2ai_dataset_ingest.sources.base import Source


class VoiceSource(Source):
    dataset_id = "bridge2ai-voice"

    def read(self) -> Iterable[Participant]:
        # TODO(next task): load TSVs, group rows by participant_id, apply YAML mappings
        # via the mapping engine, and assemble one Participant per participant_id with a
        # TimePoint per session_id.
        raise NotImplementedError("VoiceSource.read is not implemented yet")
