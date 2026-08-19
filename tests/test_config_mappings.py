"""Sanity checks that the shipped YAML mapping configs parse via the loader."""

import re
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


# ------------------------------------------------- b2ai: local-id convention (dot, not dash)

B2AI_ID = re.compile(r"\bb2ai:([A-Za-z0-9_]+)([.-])([A-Za-z0-9_]+)")


@pytest.mark.parametrize("path", VOICE_CONFIGS, ids=lambda p: p.name)
def test_config_b2ai_ids_use_dot_separator(path: Path):
    """Config assay ids must be `b2ai:<table>.<column>`, matching the SSSOM subjects.

    Both sides expand under the same `b2ai` Resource, so a config minting
    `b2ai:phq9-no_interest` while the SSSOM subject is `b2ai:phq9.no_interest` yields two
    distinct IRIs for one item — and the derived PhenotypicFeature's Evidence.reference
    then cannot be joined to the Measurement it was derived from. The dot form is the
    documented one (docs/mapping-conventions.md) and is what `hpo_rules` and
    `sssom_validate` parse, splitting on the first dot.
    """
    dashed = sorted({m.group(0) for m in B2AI_ID.finditer(path.read_text()) if m.group(2) == "-"})
    assert not dashed, f"{path.name} uses '-' in b2ai ids: {dashed}"


def test_gated_sssom_subjects_have_a_matching_config_assay():
    """Every value-gated SSSOM subject should name an item some config also emits.

    This is the join that makes provenance usable: the derived feature's evidence points at
    the same CURIE as the Measurement's assay. Subjects from tables that are not ingested
    (e.g. signs/symptoms tables with no questionnaire config) are out of scope here.
    """
    from b2ai_dataset_ingest.mapping.sssom_io import parse_sssom
    from b2ai_dataset_ingest.ontology.sssom_validate import default_mapping_files

    config_ids: set[str] = set()
    for cfg in VOICE_CONFIGS:
        config_ids |= {m.group(0) for m in B2AI_ID.finditer(cfg.read_text())}

    config_tables = {i.split(":", 1)[1].split(".", 1)[0] for i in config_ids}
    orphans = []
    for path in default_mapping_files(CONFIG_DIR.parent):
        _, rows = parse_sssom(path)
        for row in rows:
            subject = row.get("subject_id", "")
            if not row.get("when_value") or not subject.startswith("b2ai:"):
                continue  # ungated rows are pure semantics, not tied to an emitted assay
            table = subject.split(":", 1)[1].split(".", 1)[0]
            if table in config_tables and subject not in config_ids:
                orphans.append(subject)
    assert not orphans, f"gated subjects with no matching config assay id: {sorted(set(orphans))}"
