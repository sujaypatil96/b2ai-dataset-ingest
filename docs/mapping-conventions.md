# Mapping conventions

How YAML mapping configs under `config/` are authored, as implemented by
`src/b2ai_dataset_ingest/mapping/`.

## Where mappings live

- `config/<dataset>/` — per-dataset table mappings (e.g. `config/voice/demographics.yaml`).
- `config/shared/` — value sets reused across datasets (sex recodes, default taxonomy, …).

## Ontology terms

- Reference terms by **CURIE**: `MONDO:0005180`, `HP:0001609`, `LOINC:44261-6`,
  `NCBITaxon:9606`.
- Use a `{ id, label }` pair. `id` is authoritative; `label` is a human aid and may be
  filled/verified at emit time (see `src/b2ai_dataset_ingest/ontology/terms.py`).
- Placeholders use `id: "TODO"` (or `MONDO:0000000`) with `label: "TODO"` until verified.
  These are flagged before a mapping is considered complete.

## Per-table mapping shape

Common keys: `table` / `table_group` (which source table[s]), `keyed_by`
(`[participant_id, session_id]`), `produces` (the IR type). Then, by table kind:

- **Demographics** (`produces: Individual`) — a `columns` block of `<source column>:
  {target: Individual.<field>, value_map: {...}, transform: <name>}`. `value_map` recodes a
  cell (case-insensitively, code or label); `transform` normalizes it (v1: `years_to_iso8601`).
  A column that recodes to nothing is dropped; `Individual.id` comes from `participant_id`.
- **Diagnosis** (`table_group: diagnosis`) — a `conditions` map of `<file basename>:
  {id, label}` (MONDO). Membership is presence in `<basename>.tsv`. `control_handling: skip`
  leaves controls without a Disease. Unresolved conditions (placeholder id) are skipped.
- **Questionnaire** — an `items` map of `<column>: {id, label}` (the assay term, e.g. LOINC),
  plus an optional `score: {source_column, assay, unit}` for a precomputed whole-instrument
  total. Each answered item becomes an ordinal `Quantity(value=<int>, unit=UCUM {score})`.
  The answer→value map is read from the companion data dict's per-item `choices`; an
  `ordinal_scale` map is the fallback when no data dict is present (e.g. test fixtures).

## Time

- Every observation gets a `TimePoint` from its `session_id`. The reader attaches an NCIT
  term for recognized session labels (`ses-baseline`, `ses-followup`); unrecognized session
  ids (stray UUIDs) leave the `TimeElement` unset. Richer precision (timestamp, age) is used
  when present, but the synthetic data carries none.

## Term mappings to HPO (SSSOM)

Separate from the ETL configs above, `mappings/` holds **SSSOM** files that map Bridge2AI-Voice
dataset *terms* to the Human Phenotype Ontology (HPO). These are a standalone, shareable
term-to-term artifact. A row with an empty `when_value` is a pure semantic mapping (the item is
*about* the HPO concept) and produces no output. A row that carries a **`when_value`** condition
is *value-gated*: the pipeline derives a `PhenotypicFeature` from a participant's answer (see
"Conditional (value-gated) mappings" below and [ADR-0002](adr/0002-conditional-hpo-mapping.md)).

- **Namespace.** Dataset terms use the project-local `b2ai:` CURIE prefix (canonical expansions
  live in `src/b2ai_dataset_ingest/ontology/curie_map.py`, derived from the emitter's
  `Resource` registry so `b2ai:`/`HP:` mean the same thing everywhere). A subject id is
  `b2ai:<table>.<column>` — `<table>` is the data-dict file stem (unique across the tree,
  e.g. `confounders`, `phq9`, `parkinsons_disease`), `<column>` the data-dict key; they split
  on the **first** dot (stems and column names never contain a dot).

  **The same id names the same item everywhere — including the ETL configs' assay ids.** A
  questionnaire config that mints `b2ai:phq9-no_interest` while the SSSOM subject is
  `b2ai:phq9.no_interest` produces *two distinct IRIs for one item* (both expand under the
  single `b2ai` Resource), and the derived `PhenotypicFeature`'s `Evidence.reference` can
  then no longer be joined to the `Measurement` it was derived from. Use a dot, never a
  dash. Enforced by `tests/test_config_mappings.py::test_config_b2ai_ids_use_dot_separator`
  and `::test_gated_sssom_subjects_have_a_matching_config_assay`.
- **Files.** One SSSOM/TSV per domain (`b2ai-voice-signs-symptoms`, `b2ai-voice-questionnaires`),
  each self-contained: a `#`-commented SSSOM YAML metadata header (`curie_map`, `license`,
  `subject_source`, `object_source` + pinned HPO `object_source_version`, `mapping_tool`) then a
  TSV of `subject_id, subject_label, predicate_id, object_id, object_label,
  mapping_justification, confidence, comment`. SSSOM/TSV only (no JSON/RDF).
- **Predicates.** `skos:exactMatch` (same concept / exact HPO synonym), `skos:broadMatch` (the
  HPO term is *genuinely broader* and subsumes the source), `skos:narrowMatch` (HPO term is a
  subtype of the source), `skos:relatedMatch` (loose; a `comment` says why).
  `mapping_justification` is `semapv:ManualMappingCuration`. **Conflated "A or B" columns** (a
  single checkbox meaning two distinct concepts, e.g. `pneumothorax_atelectasis`) do **not**
  `broadMatch` to just one sense — that inverts the direction. Either split into one
  `narrowMatch` row per sense, or retarget to a term that truly subsumes both (e.g.
  `no_appetite` "poor appetite or overeating" → `Abnormal eating behavior`).
- **No hallucinated terms.** Every `object_id` was found by *searching HPO itself* (not guessed)
  and is re-verified by `ontology/sssom_validate.py`: it must exist and not be **deprecated**
  (checked against HPO's `owl:deprecated` flag via `adapter.obsoletes()`, not merely the
  `"obsolete "` label convention — some deprecated terms keep a normal label), and its
  `object_label` must equal HPO's authoritative label (an *exact* synonym only warns). The
  validator surfaces the loaded HPO version and warns if it differs from the file's
  `object_source_version`. It also enforces structure — known predicates, a **self-contained**
  `curie_map`, in-range confidence, no duplicate triples (across files), well-formed subjects —
  and, when a phenotype data root is supplied, that each `b2ai:` subject names a real data-dict
  column. Run it with `b2ai-ingest validate-mappings` (add `--data-root <phenotype/>` for the
  subject check); it is enforced in CI via the `validation` extra (oaklib) and
  `tests/test_sssom_mappings.py`, which also cross-checks the files with the reference `sssom-py`
  validator. Rationale: LLM-proposed ontology codes are unreliable and must be machine-checked
  before they ship (the same reason the ETL configs' MONDO/LOINC/NCIT terms are verified).

### Conditional (value-gated) mappings

A term→term mapping records that an item is *about* an HPO concept; it does not assert a
participant *has* it — that depends on the answer. Two optional columns turn a mapping into a
value-gated one that derives a `PhenotypicFeature` (per [ADR-0002](adr/0002-conditional-hpo-mapping.md)):

- **`when_value`** — a condition on the participant's answer. Grammar: comparisons `>=1`, `<=3`,
  `>0`, `<2`, `==0`, `!=0`; string equality `== "Checked"`; membership `in {1,2,3}` /
  `in {"a","b"}`; and `&` conjunction (`>=1 & <=3`). Numeric conditions are evaluated against the
  same **ordinal score** the emitted Measurement carries (resolved from the data dict's
  `choices`); string conditions against the raw cell (case-insensitively). An **empty**
  `when_value` is an inert semantic mapping — additive, changing no output.
- **`predicate_modifier`** — `Not` marks the **absent** pole (→ phenopacket
  `PhenotypicFeature.excluded = true`); empty marks present. No other value is allowed.

#### When an absent pole is justified

`excluded = true` is a strong claim, and an **unqualified** one: a phenopacket carries no time
scope on an excluded feature unless it has an `onset`. Emitted from a two-week item, it does not
say "absent over the last fortnight" — it says the participant does not have the phenotype.

So author a `Not` row only when the item's lowest answer denies that the phenotype **ever
occurred**. Three ways that fails:

- **Bounded recall.** "Not at all *in the past two weeks*" denies a fortnight, not a life. This is
  the dominant case — see *Recall windows* below; it currently disqualifies nearly every absent
  pole in the file.
- **Baseline-relative items.** "Feeling more irritated… *than usual*" — a participant who is
  always irritable answers `0`, which means *not worse than usual*, not *not irritable*.
- **Intensity- or behaviour-qualified items.** "Being extremely irritable *to the point where you
  yelled, got into fights, or destroyed things*" — `0` denies the escalation, not the emotion. It
  can support `HP:0000718` *Aggressive behavior* (whose HPO definition names those very acts) but
  not `HP:0000737` *Irritability*.

A **conflated** "A or B" item is *not* a failure on its own: `0` denies both senses, so an absent
pole is admissible even where the present pole cannot be attributed to one sense (see
`phq9.feeling_bad_self`) — provided it clears the three tests above.

The clean case is a lifetime item — "have you *ever* experienced X?" — where "no" is a genuine
lifetime denial. No gated instrument in this dataset is phrased that way.

**Recall windows.** Nearly every gated item asks about a bounded period, so `0` means *not during
that window* rather than *absent* — and the window does not survive into the output, because a
derived feature gets no `TimeElement` when the session id is an opaque hash. An `excluded = true`
built from a two-week item therefore reads as unqualified absence.

| Instrument | Window in the data dict | Published instrument |
| --- | --- | --- |
| PHQ-9, GAD-7, Leicester Cough | two weeks | two weeks |
| DSM-5 adult | mostly absent (paraphrased out) | two weeks |
| ASRS (`adhd_adult`) | none | past 6 months |
| PTSD (`ptsd_adult`) | none | past month |
| Dyspnea Index | none | no window found — unverified |

**The data dict is not authoritative here.** Three instruments record no window, but ASRS and PTSD
are bounded in their published form, so the omission is a gap in the dict rather than a property
of the instrument. Never infer that an item is unbounded from the dict's silence.

**So there is no unbounded category to fall back on.** Of the 26 absent poles in this file, 24 sit
on instruments that are certainly bounded and the remaining 2 (Dyspnea Index) are merely
unconfirmed. Every `excluded = true` the pipeline emits therefore rests on a scoped answer, and
none of that scope reaches the output.

*Undecided:* whether absent poles should be authored at all until the window can be represented
(via `PhenotypicFeature.onset`, or by not emitting `excluded` from bounded items). This is the
whole mechanism, not an edge case, so it is deferred rather than settled.

Declare `when_value` once in the file's SSSOM `extension_definitions` metadata; a present/absent
pair repeats the same `subject_id`/`predicate_id`/`object_id` and differs only in
`predicate_modifier` + `when_value` (so it is **not** a duplicate). Each derived feature is
stamped with provenance: a human-readable `description` and a GA4GH `Evidence` whose
`evidenceCode` is `ECO:0006160` ("self-reported patient statement … in automatic assertion") with
an `ExternalReference` back to the source item — self-report-derived phenotypes stay
distinguishable from clinician-observed findings. The validator checks only that `when_value`
**parses** and `predicate_modifier ∈ {"", "Not"}`; whether a cut-point is *clinically* right is a
curator judgment (see the `curation-assist` skill). The apply path lives in
`mapping/hpo_rules.py` (loader + derivation) and `mapping/conditions.py` (the grammar); the reader
runs it during questionnaire ingestion. Note the reference `sssom-py` parser **drops**
`when_value` on load, so the pipeline reads mappings with the column-preserving `parse_sssom`
in `mapping/sssom_io.py`.
