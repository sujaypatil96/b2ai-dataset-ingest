"""Ontology term resolution (STUB).

Mappings reference terms by CURIE (e.g. ``MONDO:0005180``). At emit time we may want to
attach human-readable labels. How labels are resolved (static lookup table shipped in
config/, OAK adapter, or left to the mapping author) is decided in the next task.
"""

from __future__ import annotations


def resolve_label(curie: str) -> str | None:
    """Return a human-readable label for a CURIE, or None if unknown.

    Stub: always returns None until a resolution strategy is chosen.
    """
    # TODO(next task): resolve via shipped value sets and/or an OAK adapter.
    return None
