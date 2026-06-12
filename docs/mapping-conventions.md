# Mapping conventions

How YAML mapping configs under `config/` are authored. (Stub — formalized alongside the
mapping engine in the next task.)

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

## Per-table mapping shape (current draft)

- `table` / `table_group`: which source table(s) the file covers.
- `keyed_by`: the key columns (`[participant_id, session_id]`).
- `produces`: which IR type the rows become.
- `columns` / `items` / `conditions`: the actual field-level mappings, with optional
  `value_map`, `transform`, and `ordinal_scale` helpers.

## Time

- Every observation gets a `TimePoint` derived from `session_id`. Additional time precision
  (timestamp, age) is attached when session→time metadata is available.
