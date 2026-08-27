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
mappings/       SSSOM term mappings: B2AI dataset terms (b2ai:) -> HPO, with a validator
                  derivations/  absent poles + recall windows, one YAML per instrument
docs/           design docs (SDDs), ADRs, plans, mapping conventions
tests/          fixtures + tests, incl. tests/data/multisession/ for time-course
data_synth/     (gitignored) synthetic input — see scripts/fetch_*synthetic*.sh
data/           (gitignored) source datasets, accessed under their DUAs
```

### Source vs synthetic data

Two input directories, with different handling:

| | contents | used by the pipeline? |
| --- | --- | --- |
| `data_synth/` | synthetic Voice phenotype tables; synthetic AI-READI OMOP tables | yes, by default |
| `data/` | the source datasets (B2AI-Voice, AI-READI `clinical_data`) | only in explicit runs |

Everything routine — tests, fetch scripts, CLI examples — reads from `data_synth/`. The
source datasets are used only when someone deliberately runs the pipeline against them.

That split is what the data use agreements ask for. The AI-READI Data License (WashU v2.0)
§3.C limits onward sharing, and §3.E extends the agreement's terms to derived outputs,
including synthetic data generated from the source; the B2AI-Voice PhysioNet DUA is
comparable. Developing against synthetic data keeps day-to-day work outside all of that.

**Separating ownership (recommended).** Tooling that runs under your account is
indistinguishable from you at the OS level, so the simplest way to keep routine work off
`data/` is to give it a different owner:

```bash
sudo sysadminctl -addUser b2aidata -fullName "B2AI Source Data" -home /var/empty -shell /usr/bin/false
sudo dscl . -create /Users/b2aidata IsHidden 1
sudo chown -R b2aidata:staff data out      # out/ too — its contents derive from data/
sudo chmod 700 data out                    # 700, not 750 — your account is in staff
```

Runs against the source data then go through that account, calling the venv binary
directly (`uv run` will try to write caches into an unwritable home):

```bash
sudo -u b2aidata .venv/bin/b2ai-ingest voice --input data/... --output out/
```

Undo with `sudo chown -R "$USER":staff data out && sudo chmod 755 data out`.

### Term mappings to HPO (SSSOM)

`mappings/` holds [SSSOM](https://mapping-commons.github.io/sssom/) files mapping Bridge2AI-Voice
dataset terms (a project-local `b2ai:` namespace) to the Human Phenotype Ontology — a standalone,
shareable artifact, separate from the ETL configs. A row records that an item is *about* an HPO
concept and nothing more. Every HPO code is machine-verified against a pinned HPO release (via
oaklib) so nothing is hallucinated; `b2ai-ingest validate-mappings` (and CI) enforce it. See
[docs/mapping-conventions.md](docs/mapping-conventions.md#term-mappings-to-hpo-sssom).

A row's optional `when_value` says *which answers* make the mapping applicable, so the pipeline
can derive a present `PhenotypicFeature`. What a mapping row **cannot** say is that a phenotype
is absent — the only SSSOM slot for it negates the mapping rather than the phenotype, and an
exclusion needs the instrument's recall window to bound it. Absent poles and recall windows
therefore live in [`mappings/derivations/`](mappings/derivations/README.md), one YAML per
instrument, validated by the same command. See
[ADR-0003](docs/adr/0003-separate-derivation-from-mapping.md); it is why no `excluded = true`
feature is emitted today, since Bridge2AI-Voice sessions carry no timestamp to bound one
against.

```bash
uv sync --extra validation            # install oaklib (the offline HPO backend)
uv run b2ai-ingest validate-mappings  # verify no HPO term is hallucinated / obsolete / mislabeled
```

## Getting started

```bash
uv sync                       # create the env and install deps
uv run b2ai-ingest --help     # CLI help
scripts/fetch_synthetic_data.sh   # pull the public synthetic voice data into data_synth/
```

## Development

```bash
uv run pytest        # tests
uv run ruff check    # lint
```

## License

MIT — see [LICENSE](LICENSE).
