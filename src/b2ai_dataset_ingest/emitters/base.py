"""Emitter interface.

An Emitter renders one canonical :class:`~b2ai_dataset_ingest.model.core.Participant`
into a single output artifact in some target format, and writes a collection of them to
an output directory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from b2ai_dataset_ingest.model import Participant


class Emitter(ABC):
    """Render canonical participants into a target output format."""

    #: Short identifier, e.g. "phenopacket".
    target_id: str

    @abstractmethod
    def emit(self, participant: Participant) -> object:
        """Render one participant into the target's in-memory object."""
        raise NotImplementedError

    @abstractmethod
    def write_all(self, participants: Iterable[Participant], out_dir: Path) -> int:
        """Render and write all participants to ``out_dir``; return the count written."""
        raise NotImplementedError
