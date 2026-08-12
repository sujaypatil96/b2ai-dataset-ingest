"""Propose candidate ontology terms for a concept -- the deterministic half of curation.

Given a plain-English concept (e.g. "poor appetite"), search the ontology itself and print
the real candidate terms: id, authoritative label, exact synonyms, definition, and whether the
query is an EXACT match (primary label or exact synonym). Codes come straight from the
ontology, so a curator never types an id from memory (which is how codes get hallucinated).

Pass a **CURIE** instead of a phrase to *inspect* one term you are already considering -- the
full definition, every synonym class, the editor comment, and the is_a parents. Use this
before committing a term: a label alone does not tell you the term's granularity (HPO
``Depression`` looks like a symptom but its exact synonym is "Depressive episode", i.e. a
syndrome), and the synonym list is often what justifies an ``exactMatch`` the primary label
would never suggest. See ``references/predicate-rules.md`` ("the granularity trap").

Usage:
    uv run python .claude/skills/curation-assist/scripts/search_hpo.py "poor appetite"
    uv run python .claude/skills/curation-assist/scripts/search_hpo.py HP:0000716   # inspect
    # search another ontology with:  --ontology mondo   (or loinc, ncit, ...)

Needs the `validation` extra (oaklib):  uv sync --extra validation
The first run per ontology downloads a cached SQLite; subsequent runs are offline.
"""

from __future__ import annotations

import argparse
import re
import sys

CURIE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*:[A-Za-z0-9]+$")

#: Words that, in a term's label or *exact* synonyms, suggest it denotes a syndrome/episode/
#: disorder rather than a single sign -- i.e. it may be too coarse for one questionnaire item.
#: A hint for the curator to check, never an automatic verdict.
_SYNDROME_WORDS = ("episode", "disorder", "syndrome", "disease")

SYNONYM_SLOTS = (
    ("oio:hasExactSynonym", "exact synonyms"),
    ("oio:hasNarrowSynonym", "narrow synonyms"),
    ("oio:hasBroadSynonym", "broad synonyms"),
    ("oio:hasRelatedSynonym", "related synonyms"),
)


def _granularity_hint(label: str, exact_syns: set[str]) -> str:
    """Flag a term that reads like a syndrome/episode, so a single item is not mapped to it."""
    for text in (label.lower(), *exact_syns):
        for word in _SYNDROME_WORDS:
            if word in text:
                return (
                    f"  [!] granularity: {word!r} appears in the label/exact synonyms -- this "
                    f"term may denote a syndrome, not a single sign. Check before mapping one "
                    f"questionnaire item to it (see references/predicate-rules.md)."
                )
    return ""


def inspect(adapter, curie: str) -> int:
    """Print everything a curator needs to judge one candidate term."""
    label = adapter.label(curie)
    if label is None:
        print(f"{curie} does not exist in the loaded ontology.", file=sys.stderr)
        return 1
    try:
        obsolete = curie in set(adapter.obsoletes())
    except Exception:  # noqa: BLE001 - obsolescence is advisory here; the validator is the gate
        obsolete = label.lower().startswith("obsolete")
    meta = adapter.entity_metadata_map(curie)

    print(f"{curie}  {label}" + ("   [OBSOLETE -- do not map]" if obsolete else ""))
    if definition := adapter.definition(curie):
        print(f"\n  def: {definition.strip()}")
    exact_syns: set[str] = set()
    for key, title in SYNONYM_SLOTS:
        values = [str(v) for v in (meta.get(key) or [])]
        if not values:
            continue
        if key == "oio:hasExactSynonym":
            exact_syns = {v.lower() for v in values}
        print(f"\n  {title}: {', '.join(sorted(values))}")
    for comment in meta.get("rdfs:comment") or []:
        print(f"\n  comment: {str(comment).strip()}")
    try:
        parents = [(p, adapter.label(p)) for p in adapter.hierarchical_parents(curie)]
    except Exception:  # noqa: BLE001 - hierarchy is a nicety, not the point of the command
        parents = []
    for pid, plabel in parents:
        print(f"\n  is_a -> {pid}  {plabel}")
    if hint := _granularity_hint(label, exact_syns):
        print(f"\n{hint}")
    print(
        "\nThe synonym list -- not the primary label -- is what justifies an exactMatch. "
        "Re-read the\ncolumn description against the definition above before committing "
        "(references/predicate-rules.md)."
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Search an ontology for candidate terms.")
    ap.add_argument("concept", help="plain-English concept, or a CURIE to inspect")
    ap.add_argument("--ontology", default="hp", help="hp (default), mondo, loinc, ncit, ...")
    ap.add_argument("--limit", type=int, default=8, help="max candidates to show")
    args = ap.parse_args()

    try:
        from oaklib import get_adapter
        from oaklib.datamodels.search import SearchConfiguration, SearchProperty
    except ImportError:
        print("oaklib not installed. Run: uv sync --extra validation", file=sys.stderr)
        return 2

    query = args.concept.strip()
    # A CURIE means "inspect this term", and names its own ontology -- so `search_hpo.py
    # MONDO:0002050` works without also remembering to pass --ontology mondo.
    is_curie = bool(CURIE_RE.match(query))
    ontology = query.split(":", 1)[0].lower() if is_curie else args.ontology
    adapter = get_adapter(f"sqlite:obo:{ontology}")
    if is_curie:
        return inspect(adapter, query)

    cfg = SearchConfiguration(
        properties=[SearchProperty.LABEL, SearchProperty.ALIAS], is_partial=True
    )
    prefix = ontology.upper()
    q = query.lower()

    def exact_synonyms(curie: str) -> list[str]:
        try:
            meta = adapter.entity_metadata_map(curie)
        except Exception:  # noqa: BLE001
            return []
        return [str(v) for v in meta.get("oio:hasExactSynonym", []) or []]

    hits = [c for c in adapter.basic_search(query, config=cfg) if c.startswith(prefix + ":")]
    if not hits:
        print(f"No {prefix} candidates for {query!r}. Try a broader or different phrasing.")
        return 0

    print(f"Candidates for {query!r} in {prefix} (codes come from the ontology):\n")
    for curie in hits[: args.limit]:
        label = adapter.label(curie)
        if not label or label.lower().startswith("obsolete"):
            continue
        syns = exact_synonyms(curie)
        exact = q == label.lower() or q in {s.lower() for s in syns}
        tag = "  [EXACT match]" if exact else ""
        definition = (adapter.definition(curie) or "").replace("\n", " ")
        print(f"  {curie}  {label}{tag}")
        if definition:
            print(f"      def: {definition[:150]}")
        # Show the exact synonyms: they are the evidence for (or against) an exactMatch, and
        # they are where a syndrome-level term gives itself away ("Depressive episode").
        # Capped here to keep a candidate list scannable -- inspect mode prints them all.
        if syns:
            shown = sorted(syns)[:6]
            more = f" (+{len(syns) - len(shown)} more)" if len(syns) > len(shown) else ""
            print(f"      exact synonyms: {', '.join(shown)}{more}")
        if hint := _granularity_hint(label, {s.lower() for s in syns}):
            print(f"    {hint.strip()}")
    print(
        f"\nNext: inspect the one you favour in full -- "
        f"search_hpo.py {prefix}:<id> -- then pick the concept a human agrees with, choose a\n"
        "SKOS predicate (see references/predicate-rules.md), and run the deterministic gate:\n"
        "  uv run b2ai-ingest validate-mappings --data-root <phenotype/>"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
