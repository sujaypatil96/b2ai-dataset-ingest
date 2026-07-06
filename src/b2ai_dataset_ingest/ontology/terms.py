"""Ontology term-label resolution.

Mappings reference terms by CURIE (e.g. ``MONDO:0005180``) and carry a human-readable
``label`` in the YAML config, which is the source of truth. At emit time we still want a
way to *fill* a label that a config left blank and to *verify* a config label against the
ontology. Both go through :func:`resolve_label`.

Resolution order:

1. an on-disk JSON cache (so we don't hit ontologies on every row), then
2. `oaklib <https://github.com/INCATools/ontology-access-kit>`_ if it is installed
   (an *optional* aid — ``uv pip install oaklib`` to enable), then
3. the caller-supplied ``fallback`` (typically the config label).

Because every in-scope v1 config ships a label, the emitter passes that label as the
fallback and this module never needs network access for the normal path — the oaklib
backend is there to fill/verify labels for terms a config leaves blank.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

#: Env var to override the on-disk cache location (useful in CI / tests).
CACHE_ENV = "B2AI_LABEL_CACHE"
_DEFAULT_CACHE = Path.home() / ".cache" / "b2ai-dataset-ingest" / "labels.json"

# oaklib adapter selector per CURIE prefix (semsql sqlite, downloaded + cached by oaklib).
_ADAPTERS = {
    "MONDO": "sqlite:obo:mondo",
    "HP": "sqlite:obo:hp",
    "NCIT": "sqlite:obo:ncit",
    "NCBITAXON": "sqlite:obo:ncbitaxon",
    "LOINC": "sqlite:obo:loinc",
}

_lock = threading.Lock()
_mem: dict[str, str | None] = {}
_loaded = False


def _cache_path() -> Path:
    return Path(os.environ.get(CACHE_ENV, _DEFAULT_CACHE))


def _load_cache() -> None:
    global _loaded
    if _loaded:
        return
    path = _cache_path()
    try:
        if path.exists():
            _mem.update(json.loads(path.read_text()))
    except (OSError, ValueError) as exc:  # corrupt/unreadable cache is non-fatal
        logger.debug("label cache unreadable (%s): %s", path, exc)
    _loaded = True


def _save_cache() -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_mem, indent=2, sort_keys=True))
    except OSError as exc:  # a read-only fs shouldn't break emission
        logger.debug("could not write label cache (%s): %s", path, exc)


def _oak_label(curie: str) -> str | None:
    """Look a CURIE's label up via oaklib, or None if oaklib/adapter is unavailable."""
    try:
        from oaklib import get_adapter
    except ImportError:
        return None
    prefix = curie.split(":", 1)[0].upper()
    selector = _ADAPTERS.get(prefix)
    if selector is None:
        return None
    try:
        return get_adapter(selector).label(curie)
    except Exception as exc:  # noqa: BLE001 - oaklib raises many adapter/network errors
        logger.debug("oaklib could not resolve %s: %s", curie, exc)
        return None


def resolve_label(curie: str | None, fallback: str | None = None) -> str | None:
    """Return a human-readable label for ``curie``.

    Tries the on-disk cache, then oaklib (if installed), then ``fallback``. Results
    (including "not found", cached as ``None``) are memoized on disk so repeated terms
    are free.
    """
    if not curie:
        return fallback
    _load_cache()
    with _lock:
        if curie in _mem:
            return _mem[curie] or fallback

    label = _oak_label(curie)
    with _lock:
        _mem[curie] = label
    _save_cache()
    return label or fallback
