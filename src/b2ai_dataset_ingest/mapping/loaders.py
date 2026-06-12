"""Load and validate YAML mapping configs (STUB).

A mapping config declares how one source table's columns become IR concepts. The exact
schema is finalized in the next task; for now this module just defines where configs
live and the load entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_mapping(path: Path) -> dict[str, Any]:
    """Load a single YAML mapping file into a dict.

    Validation of the mapping schema (required keys, ontology-term shape, etc.) is
    deferred to the next task.
    """
    with open(path) as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Mapping file {path} did not parse to a mapping/dict")
    return data
