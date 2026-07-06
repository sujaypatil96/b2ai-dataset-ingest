"""Deliberate multi-session / time-course coverage.

The fixture carries the same participant at two sessions; the conversion must turn those
into two time-stamped observations in one phenopacket.
"""

import csv
from pathlib import Path

from b2ai_dataset_ingest.sources.voice import VoiceSource

CONFIG_DIR = Path(__file__).parents[1] / "config" / "voice"


def test_fixture_has_two_sessions(multisession_dir: Path):
    phq9 = multisession_dir / "questionnaire" / "phq9.tsv"
    with open(phq9) as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    p1 = [r for r in rows if r["participant_id"] == "ms-0001"]
    sessions = sorted(r["session_id"] for r in p1)
    assert sessions == ["ses-baseline", "ses-followup"]


def test_multisession_yields_two_timepoints(multisession_dir: Path):
    source = VoiceSource(root=multisession_dir, config_dir=CONFIG_DIR)
    [participant] = list(source.read())
    # The same PHQ-9 measure appears at two distinct timepoints in one participant.
    times = {m.time.session_id for m in participant.measurements if m.time}
    assert times == {"ses-baseline", "ses-followup"}
    # feeling_depressed is answered at both sessions -> two Measurements for that assay.
    depressed = [
        m for m in participant.measurements if m.assay.id == "LOINC:44255-8"
    ]
    assert {m.time.session_id for m in depressed} == {"ses-baseline", "ses-followup"}
