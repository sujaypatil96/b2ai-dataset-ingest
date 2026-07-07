# b2ai-dataset-ingest

Ingest [Bridge2AI](https://bridge2ai.org/) datasets by converting their **phenotype
tables** into the [GA4GH Phenopacket](https://www.ga4gh.org/product/phenopackets/) schema.

> **"Ingest" here means: parse source data tables → emit one phenopacket per participant.**
> It does **not** build a knowledge graph (despite the Monarch/KGX sense of "ingest").

Phenopackets is the committed NIH deliverable and the first output target, but the
pipeline is deliberately **target-neutral**: mappings produce a canonical intermediate
representation (IR), and pluggable *emitters* render that IR to a target format.

```
raw tables  ->  source reader  ->  YAML mapping engine  ->  canonical IR  ->  emitter(s)
```

## Datasets

| Dataset | Status | Data |
| --- | --- | --- |
| [Bridge2AI-Voice](https://bridge2ai.org/data-voice/) | pilot / in progress | real data is PII/credentialed; we develop against public **synthetic** data ([justaddcoffee/b2ai-voice-synthetic-phenotype](https://github.com/justaddcoffee/b2ai-voice-synthetic-phenotype)) |
| [Bridge2AI AI-READi](https://bridge2ai.org/data-ai-readi/) | planned | no synthetic data yet |

## Scope (current)

Phenotype tables only:

| Source table | → | IR / Phenopacket element |
| --- | --- | --- |
| `demographics/` | → | `Individual` |
| `diagnosis/` (per-condition files) | → | `Disease` (file basename → MONDO) |
| `questionnaire/` (PHQ-9, GAD-7, VHI-10) | → | `Measurement` (per-item ordinals + precomputed totals) |
| audio / derived acoustic features | → | referenced, **not** ingested |

v1 emits `Measurement`s only; HPO `PhenotypicFeature` derivation (which needs an
ordinal→present/absent threshold policy) is a planned follow-up.

One phenopacket per participant, with **time-stamped observations** — time-course is
native to phenopackets via `TimeElement` (`PhenotypicFeature.onset`,
`Measurement.time_observed`). Each session is its own time-stamped entry. (The synthetic
data has only `ses-baseline`; multi-session handling is exercised by a dedicated test
fixture.)

## Layout

```
src/b2ai_dataset_ingest/
  model/        canonical, target-neutral intermediate representation (IR)
  sources/      dataset readers (raw tables -> IR), e.g. sources/voice/
  mapping/      YAML mapping engine (column -> concept, condition -> MONDO, item -> HPO/LOINC)
  emitters/     output writers; emitters/phenopacket.py is the first target
  ontology/     MONDO/HPO/LOINC term helpers
config/         per-dataset YAML mappings (config/voice/) + shared value sets
docs/           design docs (SDDs), ADRs, plans, mapping conventions
tests/          fixtures + tests, incl. tests/data/multisession/ for time-course
data/           (gitignored) synthetic input lands here — see scripts/fetch_synthetic_data.sh
```

## Getting started

```bash
uv sync                       # create the env and install deps
uv run b2ai-ingest --help     # CLI help
scripts/fetch_synthetic_data.sh   # pull the public synthetic voice data into data/
```

## Development

```bash
uv run pytest        # tests
uv run ruff check    # lint
```

## License

MIT — see [LICENSE](LICENSE).
