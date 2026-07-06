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
