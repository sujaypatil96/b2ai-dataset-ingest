"""Phenopacket emitter contract. Not implemented yet -> xfail until the next task."""

import pytest

from b2ai_dataset_ingest.emitters import PhenopacketEmitter
from b2ai_dataset_ingest.model import Individual, Participant


@pytest.mark.xfail(reason="PhenopacketEmitter.emit not implemented yet", raises=NotImplementedError)
def test_emit_single_participant():
    emitter = PhenopacketEmitter()
    pkt = emitter.emit(Participant(individual=Individual(id="ms-0001")))
    # Once implemented: pkt is a phenopackets.schema.v2.Phenopacket with subject.id == "ms-0001".
    assert pkt is not None
