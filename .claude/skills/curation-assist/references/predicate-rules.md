# Predicate rules — choosing the SKOS mapping predicate

> Canonical predicate *definitions* live in `docs/mapping-conventions.md`. This file is the
> **decision heuristic** for picking one, plus worked examples. Experts: add examples as
> calls get settled.

Direction is from the **subject** (the `b2ai:` dataset term) to the **object** (the ontology
term). Get the direction right — it is the most common mistake.

## Decision order (first that applies)

1. **`skos:exactMatch`** — the source term *is* the ontology concept: a verbatim label or an
   **exact** synonym, same granularity. (Not a broad/related synonym — those are not exact.)
2. **`skos:broadMatch`** — the ontology term is **genuinely broader** and *subsumes* the
   source. Typical for questionnaire item → umbrella phenotype (di_air_in "trouble getting air
   in" → Dyspnea).
3. **`skos:narrowMatch`** — the ontology term is a **subtype** of the source (the source is
   broader). E.g. general "pulmonary hypertension" → HPO *Pulmonary arterial hypertension*.
4. **`skos:relatedMatch`** — associated but not a clean hierarchical match; **always add a
   comment saying why.** Use when the source description and the ontology term only partly
   overlap.

When torn between two, pick the **weaker** one and leave a comment. Confidence convention:
exact ≈ 0.95, broad ≈ 0.8, narrow ≈ 0.75, related ≈ 0.6.

## The "A or B" conflation rule (don't invert the direction)

A single column meaning **two distinct concepts** ("pneumothorax **or** atelectasis") must
**not** `broadMatch` to just one of them — one sibling is not the *parent* of the other, so
the ontology term is *narrower* than the column, not broader. Instead:

- **Split** into one `narrowMatch` row per sense (subject repeats, objects differ), **or**
- **Retarget** to an ontology term that truly subsumes both.

## Worked examples (from real B2AI curation)

| Source (description) | Object | Predicate | Why |
| --- | --- | --- | --- |
| `shortness_breath` | HP:0002094 Dyspnea | exact | "Shortness of breath" is an exact synonym |
| `di_air_in` "trouble getting air in" | HP:0002094 Dyspnea | broad | item is a specific expression of the umbrella phenotype |
| `pulmonary_hypertension` | HP:0002092 Pulmonary arterial hypertension | narrow | HPO term is the arterial subtype |
| `no_appetite` "poor appetite **or** overeating" | HP:0100738 Abnormal eating behavior | broad | retargeted to a term that subsumes both poles |
| `stroke` "stroke **and/or** aphasia" | HP:0001297 Stroke **+** HP:0002381 Aphasia | narrow ×2 | split; each sense is narrower than the column |
| `dizziness` "lightheadedness or balance disturbance" | HP:0002321 Vertigo | related | **trap:** HPO *Vertigo* = spinning, which the source excludes — synonym match is misleading, so downgrade + comment |

## The trap to always check

If the ontology term matched only because a **word** matched (label/synonym), re-read the
source **description**. If the clinical sense differs (dizziness≠vertigo), the lexical hit is
wrong — downgrade to `relatedMatch` (or pick a better term / split), and never leave it as
`exactMatch`. Lexical match ≠ semantic match.
