"""Voice reader contract. Conversion is not implemented yet -> xfail until the next task."""

from pathlib import Path

import pytest

from b2ai_dataset_ingest.sources.voice import VoiceSource


@pytest.mark.xfail(reason="VoiceSource.read not implemented yet", raises=NotImplementedError)
def test_voice_reader_reads_participants(multisession_dir: Path):
    source = VoiceSource(root=multisession_dir, config_dir=Path("config/voice"))
    participants = list(source.read())
    # Once implemented: one Participant for the single fixture participant.
    assert len(participants) == 1
    assert participants[0].individual.id == "ms-0001"
