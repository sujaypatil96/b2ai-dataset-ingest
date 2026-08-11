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
| `panic_disorder` (a disorder) | HP:0025269 Panic attack | broad | disorder → its core phenotype; HPO term is the manifestation the disorder subsumes (cf. `anxiety_disorder`→Anxiety, `epilepsy`→Seizure) |
| `acid_reflux` "heart burn, GERD" | HP:0002020 Gastroesophageal reflux | exact | GERD is an exact synonym — a named disease *with* an exact HPO term stays exact |
| `stroke` "stroke **and/or** aphasia" | HP:0001297 Stroke **+** HP:0002381 Aphasia | narrow ×2 | split; each sense is narrower than the column |
| `dizziness` "lightheadedness or balance disturbance" | HP:0002321 Vertigo | related | **trap 1:** HPO *Vertigo* = spinning, which the source excludes — synonym match is misleading, so downgrade + comment |
| `phq9.feeling_depressed` "Feeling down, depressed, or hopeless" | HP:5200273 Pathological sadness | exact | **trap 2:** *not* HP:0000716 *Depression*, whose exact synonym is "Depressive episode" — a syndrome, not one item. HP:5200273's exact synonyms ("Down in the dumps", "Feeling hopeless all the time") match the item verbatim |
| `custom_affect_scale.sad_or_down` "Sad or down" | HP:5200273 Pathological sadness | related | same term, weaker predicate: one momentary 0–10 rating does not establish the excess in intensity/duration that makes sadness *pathological* |
| `phq9.trouble_concentrate` "Trouble concentrating… reading the newspaper or watching television" | HP:0031987 Diminished ability to concentrate | exact | exact synonyms "Concentration problems"/"Poor concentration", and the HPO definition names re-reading text without understanding — the item's own example |
| `adhd_adult.difficulty_attention` "difficulty keeping your attention when doing boring/repetitive work" | HP:0000736 Short attention span | broad | **sibling terms, don't merge:** HP:0000736 is *distractibility and impulsivity*, HP:0031987 is *failure to sustain focus*. The ASRS construct is the former, so this row stays put while the PHQ-9 one moves |

## Trap 1 — lexical match ≠ semantic match

If the ontology term matched only because a **word** matched (label/synonym), re-read the
source **description**. If the clinical sense differs (dizziness≠vertigo), the lexical hit is
wrong — downgrade to `relatedMatch` (or pick a better term / split), and never leave it as
`exactMatch`.

## Trap 2 — the granularity trap: a symptom-sounding label that denotes a *syndrome*

Trap 1 is the right level, wrong sense. This one is the right *topic*, wrong **level**: the term
names a syndrome/episode/disorder — a whole cluster of features — while your column is one item
*of* that cluster. Mapping the item to it overstates what a single answer can assert.

**Judge a term by its definition and synonyms, never by its label.** HPO `Depression`
(HP:0000716) looks like a perfect hit for "Feeling down, depressed, or hopeless". But its exact
synonym is **"Depressive episode"**, and its definition enumerates a full cluster — pessimism,
pervasive shame, low self-worth, *"thoughts of suicide and engaging in suicidal behavior"*. That
is a PHQ-9 **total score**, not PHQ-9 item 2.

```
uv run python .claude/skills/curation-assist/scripts/search_hpo.py HP:0000716
```

Inspect mode prints the full definition, every synonym class, the editor comment and the is_a
parents, and warns when *episode / disorder / syndrome / disease* shows up in the label or exact
synonyms. Treat that warning as "go read the definition", not as a verdict.

**The same check promotes as well as demotes.** The synonym list is often what justifies an
`exactMatch` the primary label would never suggest: HP:5200273 *Pathological sadness* reads
nothing like the PHQ-9 item, but its **exact** synonyms include "Down in the dumps" and "Feeling
hopeless all the time" — so that row is `exactMatch` 0.95, not `broadMatch` 0.8. Rule 1 above
says exact synonyms count; this is the reminder to actually *look at the list*.

### The column kind decides the granularity — never blanket-replace a term

The identical source words map to **different** terms depending on what kind of column it is:

| Column | Kind | Object | Why |
| --- | --- | --- | --- |
| `phq9.feeling_depressed` "Feeling down, depressed, or hopeless" | screener **item** | HP:5200273 Pathological sadness | one symptom, rated 0–3 |
| `confounders.depression_major_depressive_disorder` "Depression or major depressive disorder" | reported **diagnosis** | HP:0000716 Depression | the column *is* the syndrome, so the syndrome-level term is correct |

So when a term turns out to be wrong for one row, **classify each other row using it before
changing it** — a find-and-replace across the mapping files would have broken the second row
here. (Real example: PR #10 review, 5 symptom rows moved off HP:0000716, 2 diagnosis rows
deliberately kept.)

The same discipline applies when the two candidates are **siblings** rather than different
levels. HP:0000736 *Short attention span* (distractibility + impulsivity) and HP:0031987
*Diminished ability to concentrate* (failure to sustain focus) share a parent and read alike,
but they are different constructs: the PHQ-9/PHQ-A "trouble concentrating" items belong to the
second, while the ASRS inattention item belongs to the first. Three rows used HP:0000736; two
moved and one stayed. **When you keep a row that a reviewer might expect to change, say so in
its `comment`** — otherwise it reads as an oversight rather than a decision.

### Check whether the term is contested

Before leaning on a term for many rows, search the ontology's issue tracker. HP:0000716 is
[proposed for renaming to *Depressive Episode*](https://github.com/obophenotype/human-phenotype-ontology/issues/11460)
— filed precisely because "Mania and Depression lean towards a disease rather than a phenotype".
A pending rename is two warnings at once: the term is semantically contested, and when the
rename lands `validate-mappings` will fail every row whose `object_label` still says
`Depression`. That failure is the guardrail working — but better to not build on sand.

### Cross-check against an independent curation, when one exists

For **standard instruments** (PHQ-9, GAD-7, MADRS, …) someone may have already curated
item→HPO mappings. Diffing against one is a far stronger check than "does the code resolve",
because it surfaces *omissions* and *judgment differences*, which no validator can catch.
[`rorschach-rs`](https://github.com/SmartMonkey-git/rorschach-rs) (`src/presets/*.rs`) carries
Robinson-group mappings for PHQ-9, GAD-7, ASRM, YMRS, MADRS and HAM-A. Treat a disagreement as
a question to resolve, not an error — but resolve it explicitly.
