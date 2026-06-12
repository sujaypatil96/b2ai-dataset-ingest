"""Deliberate multi-session / time-course coverage.

The fixture file itself is checked today (it really does carry two sessions for one
participant). The end-to-end conversion that turns those into two time-stamped
observations is xfail until the reader/emitter exist.
"""

import csv
from pathlib import Path

import pytest

from b2ai_dataset_ingest.sources.voice import VoiceSource


def test_fixture_has_two_sessions(multisession_dir: Path):
    phq9 = multisession_dir / "questionnaire" / "phq9.tsv"
    with open(phq9) as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    p1 = [r for r in rows if r["participant_id"] == "ms-0001"]
    sessions = sorted(r["session_id"] for r in p1)
    assert sessions == ["ses-baseline", "ses-followup"]


@pytest.mark.xfail(reason="end-to-end conversion not implemented yet", raises=NotImplementedError)
def test_multisession_yields_two_timepoints(multisession_dir: Path):
    source = VoiceSource(root=multisession_dir, config_dir=Path("config/voice"))
    [participant] = list(source.read())
    # Once implemented: the same PHQ-9 measure appears at two distinct timepoints.
    times = {m.time.session_id for m in participant.measurements if m.time}
    assert times == {"ses-baseline", "ses-followup"}
