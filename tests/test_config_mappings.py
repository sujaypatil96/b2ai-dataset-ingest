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
