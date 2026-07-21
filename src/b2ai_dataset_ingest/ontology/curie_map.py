"""Canonical CURIE prefix -> URI-namespace expansions for the project.

Single source of truth shared by (a) the SSSOM mapping-set headers under ``mappings/`` and
(b) the SSSOM validator (:mod:`b2ai_dataset_ingest.ontology.sssom_validate`). The ontology and
``b2ai`` expansions are derived from :data:`ontology.resources.KNOWN_RESOURCES` so the CURIE
namespace agrees with what the phenopacket emitter already declares in each packet's MetaData
-- there is exactly one place that decides what ``b2ai:`` or ``HP:`` expands to.

``b2ai`` is the project-local namespace for Bridge2AI-Voice dataset *terms* (data-dictionary
columns), used as the ``subject`` side of the B2AI -> HPO mappings; e.g.
``b2ai:confounders.dizziness`` ->
``https://github.com/sujaypatil96/b2ai-dataset-ingest#confounders.dizziness``.
"""

from __future__ import annotations

from collections.abc import Iterable

from b2ai_dataset_ingest.ontology.resources import KNOWN_RESOURCES, prefix_of

#: Namespace prefix for Bridge2AI-Voice dataset terms (the SSSOM ``subject`` side).
B2AI_PREFIX = "b2ai"

# Mapping / provenance vocabularies that SSSOM needs but that are not ontology Resources.
_VOCAB: dict[str, str] = {
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "semapv": "https://w3id.org/semapv/vocab/",
    "sssom": "https://w3id.org/sssom/",
    "orcid": "https://orcid.org/",
    "github": "https://github.com/",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    # OBO base, used by SSSOM metadata like `object_source: obo:hp`.
    "obo": "http://purl.obolibrary.org/obo/",
}

#: prefix -> URI-namespace. Ontology/``b2ai`` expansions come from the emitter's Resource
#: registry (keyed by canonical ``namespace_prefix``, e.g. ``HP``, ``NCBITaxon``, ``b2ai``).
CURIE_MAP: dict[str, str] = {
    **_VOCAB,
    **{res["namespace_prefix"]: res["iri_prefix"] for res in KNOWN_RESOURCES.values()},
}


def expand(curie: str) -> str | None:
    """Expand a CURIE to a full URI using :data:`CURIE_MAP`, or None if the prefix is unknown.

    Prefix lookup is case-insensitive against the canonical prefixes (so ``hp:0002094`` and
    ``HP:0002094`` both resolve), but the returned URI uses the registered namespace.
    """
    if ":" not in curie:
        return None
    prefix, reference = curie.split(":", 1)
    base = CURIE_MAP.get(prefix)
    if base is None:  # try a case-insensitive match against the canonical prefixes
        lowered = prefix.lower()
        for known, uri in CURIE_MAP.items():
            if known.lower() == lowered:
                base = uri
                break
    return None if base is None else f"{base}{reference}"


def curie_map_for(prefixes: Iterable[str]) -> dict[str, str]:
    """Return the subset of :data:`CURIE_MAP` for ``prefixes`` (for a minimal SSSOM header).

    Raises ``KeyError`` if a prefix is not registered -- a mapping file must not reference a
    namespace the project cannot expand.
    """
    return {p: CURIE_MAP[p] for p in prefixes}


__all__ = ["B2AI_PREFIX", "CURIE_MAP", "expand", "curie_map_for", "prefix_of"]
