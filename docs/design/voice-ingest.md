# SDD: Bridge2AI-Voice phenotype → phenopacket pipeline

- **Status:** Implemented (v1)
- **Author(s):** Sujay Patil
- **Date:** 2026-06-12 (v1 implemented 2026-07-06)

## 1. Overview & problem statement

Convert the Bridge2AI-Voice `phenotype/` tables into one GA4GH phenopacket per participant,
with time-stamped observations. Developed against public synthetic data
([justaddcoffee/b2ai-voice-synthetic-phenotype](https://github.com/justaddcoffee/b2ai-voice-synthetic-phenotype));
the real data is PII/credentialed.

## 2. Goals & non-goals

- **Goals:** demographics → `Individual`; diagnosis → `Disease` (MONDO); questionnaires →
  `Measurement` (scores) + `PhenotypicFeature` (HPO); one phenopacket per participant;
  time-course via `TimeElement` per session.
- **Non-goals (now):** audio/derived-feature ingestion (referenced only); `enrollment/`,
  `confounders/`, `pediatric*`, `task/` tables; AI-READi.

## 3. Design

Implements the project architecture (see
[ADR-0001](../adr/0001-name-architecture-tooling.md)):
`VoiceSource` reads the TSVs, the YAML mapping engine (`config/voice/`) turns rows into IR
objects grouped by `participant_id`, and `PhenopacketEmitter` renders each participant.

## 4. Data model / mappings

- Tables keyed by `participant_id` + `session_id`; companion ReproSchema JSON data dicts
  provide per-item `choices` (the answer→value map) and `termURL` codings.
- Rows are **not** unique per `(participant_id, session_id)`: the reader groups by that key
  and merges duplicates "last non-empty wins" (logging a warning). Demographics are grouped
  by participant and merged into one `Individual`.
- `diagnosis/<condition>.tsv` basename → MONDO term (`config/voice/diagnosis.yaml`). A
  Disease is emitted only for conditions with a *resolved* MONDO term; placeholder
  (`MONDO:0000000`/`TODO`) conditions are skipped with a warning. `control` is skipped.
- Questionnaire items → ordinal `Measurement` (`Quantity(value=<int>, unit=UCUM {score})`);
  a precomputed whole-instrument total → `Measurement` only when the source ships one
  (VHI-10's `vhi_10_calc_score`; PHQ-9/GAD-7 ship none). **No HPO `PhenotypicFeature`
  in v1** — the ordinal→present/absent threshold policy is deferred.
- `session_id` → `TimePoint` → `TimeElement`, using the session label's NCIT term
  (`ses-baseline` → `NCIT:C25213`, `ses-followup` → `NCIT:C16033`). There are no real
  dates/ages in the data; stray UUID sessions leave the `TimeElement` unset. Synthetic data
  is effectively single-session (`ses-baseline`); multi-session is exercised by
  `tests/data/multisession/`.
- **MetaData** carries one versioned `Resource` per ontology prefix actually used
  (`ontology/resources.py`); the emitter fails loudly (warns) if a prefix is unregistered.
- **Ontology labels**: config `{id, label}` pairs are the source of truth; `ontology/terms.py`
  can *fill/verify* blank labels via oaklib (optional — `uv pip install oaklib`) with an
  on-disk cache. All in-scope CURIEs were verified against EBI OLS4 / the NLM LOINC service
  on 2026-07-06 (this caught three wrong codes proposed during planning — see git history).

## 5. Testing strategy

- Unit: `tests/test_mapping_engine.py` (recode/transform, ordinal from data-dict `choices`
  vs `ordinal_scale` fallback, precomputed total), `tests/test_ir_model.py`,
  `tests/test_config_mappings.py`.
- Reader/emitter: `tests/test_voice_reader.py`, `tests/test_phenopacket_emitter.py`
  (Disease/Measurement/TimeElement building; UUID session → time unset), and
  `tests/test_multisession.py` (same measure at two timepoints in one phenopacket).
- End-to-end: `tests/test_end_to_end.py` — the multisession fixture and a slice of the real
  synthetic data both round-trip through `google.protobuf.json_format.Parse`, and every
  emitted packet's `MetaData` declares a `Resource` for every ontology prefix it uses.
  (The real-data test skips when the synthetic tables haven't been fetched.)

## 6. Risks & mitigations

- Wide/sparse tables → map only needed columns; ignore the rest.
- Synthetic data is non-coherent across tables → don't assume cross-table consistency.
- Ontology term accuracy (MONDO/LOINC/NCIT) → every in-scope CURIE verified against public
  ontology services (EBI OLS4, NLM LOINC) before acceptance.

## 7. Open questions (resolved for v1)

- **Label resolution** → config `{id, label}` is authoritative; oaklib fills/verifies blank
  labels via the optional `ontology` extra with an on-disk cache (`ontology/terms.py`).
- **`control` participants** → skipped (Individual + measurements, no Disease).
- **Ordinal answer modeling** → `Quantity(value=<int>, unit=UCUM {score})`; the IR keeps
  `value_term` for future genuinely-categorical items.
- Still open: whether to promote the IR to a LinkML schema; adding HPO
  `PhenotypicFeature` derivation (needs an ordinal→present/absent threshold policy).
