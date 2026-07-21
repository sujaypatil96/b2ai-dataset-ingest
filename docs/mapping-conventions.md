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
term-to-term artifact; they are **not** (yet) consumed by the emitter — deriving
`PhenotypicFeature`s from them needs an ordinal→present/absent threshold policy and is a
follow-up.

- **Namespace.** Dataset terms use the project-local `b2ai:` CURIE prefix (canonical expansions
  live in `src/b2ai_dataset_ingest/ontology/curie_map.py`, derived from the emitter's
  `Resource` registry so `b2ai:`/`HP:` mean the same thing everywhere). A subject id is
  `b2ai:<table>.<column>` — `<table>` is the data-dict file stem (unique across the tree,
  e.g. `confounders`, `phq9`, `parkinsons_disease`), `<column>` the data-dict key; they split
  on the **first** dot (stems and column names never contain a dot).
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
