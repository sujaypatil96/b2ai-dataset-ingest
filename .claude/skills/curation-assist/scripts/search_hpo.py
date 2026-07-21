"""Propose candidate ontology terms for a concept -- the deterministic half of curation.

Given a plain-English concept (e.g. "poor appetite"), search the ontology itself and print
the real candidate terms: id, authoritative label, definition, and whether the query is an
EXACT match (primary label or exact synonym). Codes come straight from the ontology, so a
curator never types an id from memory (which is how codes get hallucinated).

Usage:
    uv run python .claude/skills/curation-assist/scripts/search_hpo.py "poor appetite"
    # search another ontology with:  --ontology mondo   (or loinc, ncit, ...)

Needs the `validation` extra (oaklib):  uv sync --extra validation
The first run per ontology downloads a cached SQLite; subsequent runs are offline.
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Search an ontology for candidate terms.")
    ap.add_argument("concept", help="plain-English concept to search for")
    ap.add_argument("--ontology", default="hp", help="hp (default), mondo, loinc, ncit, ...")
    ap.add_argument("--limit", type=int, default=8, help="max candidates to show")
    args = ap.parse_args()

    try:
        from oaklib import get_adapter
        from oaklib.datamodels.search import SearchConfiguration, SearchProperty
    except ImportError:
        print("oaklib not installed. Run: uv sync --extra validation", file=sys.stderr)
        return 2

    adapter = get_adapter(f"sqlite:obo:{args.ontology}")
    cfg = SearchConfiguration(
        properties=[SearchProperty.LABEL, SearchProperty.ALIAS], is_partial=True
    )
    prefix = args.ontology.upper()
    q = args.concept.strip().lower()

    def exact_synonyms(curie: str) -> set[str]:
        try:
            meta = adapter.entity_metadata_map(curie)
        except Exception:  # noqa: BLE001
            return set()
        return {str(v).lower() for v in meta.get("oio:hasExactSynonym", []) or []}

    hits = [c for c in adapter.basic_search(args.concept, config=cfg) if c.startswith(prefix + ":")]
    if not hits:
        print(f"No {prefix} candidates for {args.concept!r}. Try a broader or different phrasing.")
        return 0

    print(f"Candidates for {args.concept!r} in {prefix} (codes come from the ontology):\n")
    for curie in hits[: args.limit]:
        label = adapter.label(curie)
        if not label or label.lower().startswith("obsolete"):
            continue
        exact = q == label.lower() or q in exact_synonyms(curie)
        tag = "  [EXACT match]" if exact else ""
        definition = (adapter.definition(curie) or "").replace("\n", " ")
        print(f"  {curie}  {label}{tag}")
        if definition:
            print(f"      def: {definition[:150]}")
    print(
        "\nNext: pick the concept a human agrees with, choose a SKOS predicate "
        "(see references/predicate-rules.md), then run the deterministic gate:\n"
        "  uv run b2ai-ingest validate-mappings --data-root <phenotype/>"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
