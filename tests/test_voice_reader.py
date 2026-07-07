"""Voice reader: fixture TSVs -> canonical Participants."""

from pathlib import Path

from b2ai_dataset_ingest.sources.voice import VoiceSource

CONFIG_DIR = Path(__file__).parents[1] / "config" / "voice"


def _write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(header)] + ["\t".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n")


def test_voice_reader_reads_participants(multisession_dir: Path):
    source = VoiceSource(root=multisession_dir, config_dir=CONFIG_DIR)
    participants = list(source.read())
    # One Participant for the single fixture participant.
    assert len(participants) == 1
    participant = participants[0]
    assert participant.individual.id == "ms-0001"
    assert participant.source_dataset == "bridge2ai-voice"


def test_voice_reader_populates_individual_and_disease(multisession_dir: Path):
    source = VoiceSource(root=multisession_dir, config_dir=CONFIG_DIR)
    [participant] = list(source.read())
    # Demographics -> Individual (age + sex).
    assert participant.individual.age_iso8601 == "P63Y"
    assert participant.individual.sex == "MALE"
    # diagnosis/parkinsons_disease.tsv -> one Disease with the resolved MONDO term.
    assert [d.term.id for d in participant.diseases] == ["MONDO:0005180"]


def test_participant_only_in_unresolved_diagnosis_still_emitted(tmp_path: Path):
    # A participant whose only appearance is a not-yet-coded (placeholder) diagnosis file
    # must still enter the universe as an id-only Individual (no Disease), not be dropped.
    _write_tsv(
        tmp_path / "diagnosis" / "anxiety.tsv",  # anxiety -> MONDO:0000000 placeholder
        ["participant_id", "session_id"],
        [["only-anxiety", "ses-baseline"]],
    )
    participants = list(VoiceSource(root=tmp_path, config_dir=CONFIG_DIR).read())
    ids = {p.individual.id for p in participants}
    assert "only-anxiety" in ids
    [p] = [p for p in participants if p.individual.id == "only-anxiety"]
    assert p.diseases == []  # placeholder condition contributes no Disease


def test_control_only_participant_gets_individual_no_disease(tmp_path: Path):
    _write_tsv(
        tmp_path / "diagnosis" / "control.tsv",
        ["participant_id", "session_id"],
        [["only-control", "ses-baseline"]],
    )
    [participant] = list(VoiceSource(root=tmp_path, config_dir=CONFIG_DIR).read())
    assert participant.individual.id == "only-control"
    assert participant.diseases == []
