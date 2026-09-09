# SDD: Bridge2AI AI-READI (OMOP CDM) → phenopacket pipeline

- **Status:** Implemented (v1)
- **Author(s):** Sujay Patil
- **Date:** 2026-09-09

## 1. Overview & problem statement

Convert the AI-READI `clinical_data/` tables into one GA4GH phenopacket per participant.
AI-READI is the second dataset named in [ADR-0001](../adr/0001-name-architecture-tooling.md),
and it exercises the IR + pluggable-emitter claim for the first time: its clinical payload is
**OMOP CDM v5.4 in CSV**, not the wide ReproSchema TSVs the Voice pipeline was built for.

Developed against the 100-participant "mini" release (`data/aireadi-mini/`, licensed, local
only) and a hand-authored fixture (`tests/data/aireadi/`, committed, synthetic by
construction).

## 2. Goals & non-goals

- **Goals:** `participants.tsv` + `person.csv` → `Individual`; `visit_occurrence` →
  `TimePoint`; `condition_occurrence` → `Disease` (MONDO); `measurement` → `Measurement`
  with UCUM units, per-row reference ranges and per-eye laterality; one phenopacket per
  participant; a PHI-safe preflight (`validate-aireadi`) and run report.
- **Non-goals (now):** `observation.csv` (355 items — the CES-D-10 and PAID-5 instruments,
  the medical-history yes/no grid, the PhenX SDOH modules, the imaging-acquisition flags);
  `procedure_occurrence.csv` (monofilament testing); the eight non-clinical modality
  directories; medications (the release ships no `drug_exposure` table); race/ethnicity.

## 3. Design

`AireadiSource` (`src/b2ai_dataset_ingest/sources/aireadi/reader.py`) streams each OMOP CSV,
`mapping/omop.py` turns a long row into an IR fragment, and the existing
`PhenopacketEmitter` renders each participant. `participants.tsv` is the one wide table and
feeds the *existing* `MappingEngine.individual_fields` `columns:` path unchanged.

`mapping/omop.py` sits in `mapping/`, not in `sources/aireadi/`, because OMOP CDM is a
published standard: a second OMOP dataset reuses the module and writes only its own config.

## 4. Data model / mappings

- **The item key is the REDCap variable**, taken from the text before the first comma of
  `<domain>_source_value` — never `*_concept_id`. Verified against the release: concept
  `3004249` backs both `bp1_sysbp_vsorres` and `bp2_sysbp_vsorres`, `3012888` both diastolic
  readings, `4239408` both pulse readings, and `4047085` all twenty monofilament sites. Every
  variable maps to exactly one concept, but not the reverse.
- **`*_source_value` is truncated at 49 characters**, so its label half is a curator hint and
  never a label source. Untruncated condition names come from the parallel `observation` row's
  `qualifier_source_value`.
- **Subjects and assay ids are `b2ai:<omop_table>.<redcap_var>`.** The table qualifier is
  mandatory: all 28 `condition_occurrence` variables also appear in `observation`, where they
  are a self-reported yes/no answer rather than an asserted condition.
- **No `Disease.onset`.** `condition_start_date == condition_end_date` on all 557 rows and
  equals one of that participant's medical-history survey dates — it is the form-fill date.
  Emitting it as onset would assert a false natural history a consumer could not detect.
- **`study_group` is a Measurement, not a Disease.** The arm disagrees with the participant's
  own condition table for 9 of 100 participants, so asserting it as a diagnosis would state
  something the clinical data does not support. It is also recorded on `Participant.cohort`.
- **Units are declared per item in config; the data column is a cross-check.**
  `unit_source_value` is blank or a bare space on 7712 of 10407 rows and `"N/A"` on 372 more;
  every non-lab family keeps its unit inside the truncated label. `Quantity.unit` is required
  by the schema, so a value whose unit resolves to nothing is dropped and counted.
- **Laterality is declared per item, not read from `qualifier_concept_id`.** Six
  autorefraction items are per-eye by name and carry no qualifier at all (573 rows), and the
  same column on a medical-history row holds a *condition name*. It goes on
  `Measurement.procedure.body_site`, the only laterality slot a GA4GH `Measurement` has.
- **A reference range is emitted only when both bounds are present.** `ReferenceRange.low`
  and `.high` are proto3 doubles with no field presence, so a one-sided range would read back
  as "the normal range is 39 to 0". Opt-in per item: non-lab rows reuse the same columns for
  an item's *scoring* range (MoCA naming is 0–3), which is not a reference interval.
- **Censoring.** `operator_concept_id 4171756` (`<`) marks a bounded result; GA4GH `Quantity`
  has no operator slot, so those rows are dropped and counted rather than reported as
  measured. Note the polarity: the column is `0` ("not recorded") on 4800 of 10407 rows, so a
  "must equal `=`" gate would have deleted every ophthalmic, vital and CBC row.
- **Sentinels.** `555`/`777`/`888`/`999` in `value_as_number` are REDCap refusal codes and are
  dropped. `0` is *not* a sentinel in a value column — it is a valid answer — while `0` in a
  `*_concept_id` column means "no matching concept". Two separate null sets.
- **Time.** `time_precision: age` is the default, so every emitted `TimeElement` carries an
  Age and no date leaves the machine: day-precision dates are HIPAA identifiers and the
  licence extends to derived output. `date`/`datetime` are opt-in and normalize to RFC3339-Z
  — protobuf rejects every other spelling and the emitter *catches* the error and falls back,
  so an un-normalized value would lose every `time_observed` silently.
- **Sex is unavailable in this release.** `gender_concept_id` is `0` on all 100 rows and every
  `*_source_value` is blank. `person.yaml` is written for the full release and recodes `0` to
  nothing; the redaction is reported so 100 `UNKNOWN_SEX` subjects cannot read as success.

## 5. Testing strategy

Three tiers, because the Voice two-tier pattern does not transfer — the VUMC synthetic
release ships two of the six tables and so covers *less* than the hand fixture.

- **Tier 1, always run, in CI:** `tests/data/aireadi/` (4 participants, ~30 rows), every row
  encoding one real-data trap; see that directory's README. Covered by
  `tests/test_aireadi_omop.py` (primitives, no data on disk) and
  `tests/test_aireadi_reader.py`.
- **Tier 2, local:** the VUMC synthetic release — asserts graceful degradation to
  `tables_missing` when four of six tables are absent.
- **Tier 3, local:** the real mini release — the only tier that runs `validate-aireadi`
  against the full six-table shape with `--strict-coverage` and requires zero errors.

No golden/snapshot phenopackets: verification is a protobuf round-trip plus structural
invariants (`_prefixes_used(pkt) <= declared`, and no `TODO` CURIE in any emitted packet).

**Nothing AI-READI-derived is committed.** The AI-READI Data License extends to data that has
been "excerpted or otherwise altered", so fixtures are hand-authored rather than sampled, and
there is no `examples/phenopackets/aireadi-*/` counterpart to the Voice examples.

## 6. Risks & mitigations

- **No OMOP `CONCEPT` table ships and the Athena API returns HTTP 403 here**, so no
  `concept_id → CURIE` resolution is free. Every emitted code is curated and machine-checked:
  MONDO via the existing oaklib gate, LOINC via the NLM Clinical Table service (the route
  `phq9.yaml` already used).
- **LOINC cannot be an SSSOM `object_source`**: `sqlite:obo:loinc` resolves to a 0-byte
  database. LOINC assay codes therefore live in the YAML config with a dated verification
  header rather than behind a gate that cannot check them.
- **Partial mapping is the steady state.** 32 measurement items (MoCA, monofilament) and 4
  conflated conditions are deliberately unmapped; they are counted per item on the report, and
  `has_degradation` deliberately excludes them so the flag stays meaningful.
- **Scale.** Materializing the 117 MB synthetic `measurement.csv` costs 1206 MB of RSS against
  18 MB streamed, so every table is read row by row.

## 7. Open questions

- **Date precision** — `time_precision: age` is the shipped default; whether day-precision
  dates may be emitted is a DUA question, not a code question.
- **The 2498 explicit medical-history negatives** in `observation.csv` would give
  `excluded: true` Diseases. The data is unusually clean (an exact bijection with
  `condition_occurrence`) and, unlike the Voice questionnaires, these are lifetime-scoped
  items — so the reason the absent pole was withdrawn for Voice does not apply. Still off
  pending clinical review.
- **The four conflated conditions** (`mhoccur_ua`, `mhoccur_cvdot`, `mhoccur_circ`, and the
  lab-finding `mh_a1c`) need a curator's call on what was actually asked.
- **The LOINC upgrade tranche** — ~40 items currently carry `b2ai:` local assay ids and can be
  swapped for verified LOINC codes in place, changing no code.
