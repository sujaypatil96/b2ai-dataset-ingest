"""Source interface.

A Source knows how to read one dataset's on-disk layout (which tables exist, how they
are keyed) and, using the YAML mapping engine, turn it into a list of canonical
:class:`~b2ai_dataset_ingest.model.core.Participant` objects. It does not know anything
about output formats.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from b2ai_dataset_ingest.model import Participant


class Source(ABC):
    """Read a dataset directory and yield canonical participants."""

    #: Stable identifier recorded in output metadata, e.g. "bridge2ai-voice".
    dataset_id: str

    def __init__(self, root: Path, config_dir: Path) -> None:
        self.root = Path(root)
        self.config_dir = Path(config_dir)

    @abstractmethod
    def read(self) -> Iterable[Participant]:
        """Parse the dataset into canonical participants. One per ``participant_id``."""
        raise NotImplementedError
