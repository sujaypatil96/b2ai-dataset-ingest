"""Mapping engine contract. Not implemented yet -> xfail until the next task."""

import pytest

from b2ai_dataset_ingest.mapping.engine import MappingEngine


@pytest.mark.xfail(reason="MappingEngine.apply not implemented yet", raises=NotImplementedError)
def test_apply_row():
    engine = MappingEngine(mapping={"table": "phq9"})
    result = engine.apply({"participant_id": "ms-0001", "session_id": "ses-baseline"})
    assert result is not None
