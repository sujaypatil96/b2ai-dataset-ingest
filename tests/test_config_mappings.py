"""Sanity checks that the shipped YAML mapping configs parse via the loader."""

from pathlib import Path

import pytest

from b2ai_dataset_ingest.mapping.loaders import load_mapping

CONFIG_DIR = Path(__file__).parents[1] / "config"
VOICE_CONFIGS = sorted(CONFIG_DIR.glob("voice/**/*.yaml"))


def test_voice_configs_exist():
    names = {p.name for p in VOICE_CONFIGS}
    assert {"demographics.yaml", "diagnosis.yaml", "phq9.yaml"} <= names


@pytest.mark.parametrize("path", VOICE_CONFIGS, ids=lambda p: p.name)
def test_mapping_parses(path: Path):
    data = load_mapping(path)
    assert isinstance(data, dict)
    assert data  # non-empty


# --------------------------------------------------- configs vs the real synthetic tables

SYNTHETIC = (
    Path(__file__).parents[1]
    / "data_synth"
    / "b2ai-voice-synthetic-phenotype"
    / "output"
    / "phenotype"
)


@pytest.mark.skipif(
    not SYNTHETIC.is_dir(),
    reason="synthetic data not fetched (run scripts/fetch_synthetic_data.sh)",
)
def test_shipped_configs_validate_against_synthetic_data():
    """The shipped configs must preflight cleanly against the public synthetic tables.

    This is the guard the hand-built fixtures cannot provide: ``tests/data/multisession``
    is edited whenever a config changes, so it always agrees with the config and can never
    catch a column that the *real* tables do not have. Renaming demographics' sex column to
    one the synthetic release does not ship made ``b2ai-ingest validate`` exit 1 while the
    whole suite stayed green — this test closes that gap.
    """
    from b2ai_dataset_ingest.sources.voice.validate import validate_voice

    report = validate_voice(root=SYNTHETIC, config_dir=CONFIG_DIR / "voice")
    assert not report.errors, "\n".join(f"{f.table}: {f.message}" for f in report.errors)


# ------------------------------------------------------ demographics sex column precedence


@pytest.mark.parametrize(
    ("assigned", "at_birth", "expected"),
    [
        ("Female", "Male", "MALE"),  # both filled: the preferred column wins
        ("Female", "", "FEMALE"),  # only the fallback: still resolved
        ("", "Male", "MALE"),  # only the preferred column (synthetic-style release)
        ("", "", None),  # neither: sex left unset, not defaulted
    ],
)
def test_sex_column_precedence(assigned: str, at_birth: str, expected: str | None):
    """`sex_at_birth` wins where filled; `sex_assigned_at_birth` is the fallback.

    Both columns map to Individual.sex and precedence is expressed purely by declaration
    order in demographics.yaml, so this pins that ordering against the *shipped* config.
    Releases differ in which columns they carry: the real b2aiprep tables have both, the
    public synthetic tables only `sex_assigned_at_birth`.
    """
    from b2ai_dataset_ingest.mapping.engine import MappingEngine

    engine = MappingEngine(load_mapping(CONFIG_DIR / "voice" / "demographics.yaml"))
    fields = engine.individual_fields(
        {"sex_assigned_at_birth": assigned, "sex_at_birth": at_birth}
    )
    assert fields.get("sex") == expected
