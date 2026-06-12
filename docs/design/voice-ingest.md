# SDD: Bridge2AI-Voice phenotype → phenopacket pipeline

- **Status:** Draft (stub — fleshed out as the conversion is implemented)
- **Author(s):** Sujay Patil
- **Date:** 2026-06-12

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
  provide per-item `choices` and `termURL` codings.
- `diagnosis/<condition>.tsv` basename → MONDO term (`config/voice/diagnosis.yaml`).
- Questionnaire items → ordinal `Measurement` and/or HPO `PhenotypicFeature`; whole-instrument
  scores → `Measurement` (e.g. VHI-10 reads `vhi_10_calc_score`).
- `session_id` → `TimePoint` → `TimeElement`. Synthetic data is single-session
  (`ses-baseline`); multi-session is exercised by `tests/data/multisession/`.

## 5. Testing strategy

`tests/test_voice_reader.py`, `tests/test_phenopacket_emitter.py`, and
`tests/test_multisession.py` (currently `xfail` pending implementation), plus
`tests/test_config_mappings.py` and `tests/test_ir_model.py` which pass today.

## 6. Risks & mitigations

- Wide/sparse tables → map only needed columns; ignore the rest.
- Synthetic data is non-coherent across tables → don't assume cross-table consistency.
- Ontology term accuracy (MONDO/HPO/LOINC) → all CURIEs reviewed before acceptance.

## 7. Open questions

- Label resolution strategy (shipped value sets vs OAK) — see `ontology/terms.py`.
- `control` participants: skip vs. `excluded=true` disease.
- Whether to promote the IR to a LinkML schema.
