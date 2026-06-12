"""Output-target writers. Each emitter renders the canonical IR into one target format."""

from b2ai_dataset_ingest.emitters.base import Emitter
from b2ai_dataset_ingest.emitters.phenopacket import PhenopacketEmitter

__all__ = ["Emitter", "PhenopacketEmitter"]
