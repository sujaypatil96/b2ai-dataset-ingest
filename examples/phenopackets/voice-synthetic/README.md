# Example phenopackets — Bridge2AI-Voice (synthetic)

173 GA4GH Phenopackets (schema v2), one JSON file per participant, named
`<participant_id>.json`. They are here so colleagues can exercise downstream tooling
against realistic phenopacket structure **without needing credentialed access to the
real dataset**.

> **Synthetic only.** Every participant here is fabricated. Nothing in this folder derives
> from the credentialed PhysioNet Bridge2AI-Voice download; participant IDs are the
> synthetic UUIDs, not the real record IDs. Do not treat these as clinical data — the
> values are statistically plausible but not real observations.

## Provenance

| | |
| --- | --- |
| Input | [justaddcoffee/b2ai-voice-synthetic-phenotype](https://github.com/justaddcoffee/b2ai-voice-synthetic-phenotype) @ `4338b26` (`output/phenotype/`) |
| Generator | `b2ai-dataset-ingest` 0.0.1 @ `55358c2` |
| Emitter | `phenopacket` (`src/b2ai_dataset_ingest/emitters/phenopacket.py`) |
| Config | `config/voice/` |

## Contents

| | count |
| --- | --- |
| phenopackets (participants) | 173 |
| `Disease` entries | 669 |
| `Measurement` entries | 891 |
| `PhenotypicFeature` entries | 104 |

Source tables read: `demographics`, `adhd_adult`, `custom_affect_scale`, `dsm5_adult`,
`dyspnea_index`, `gad7_anxiety`, `leicester_cough_questionnaire`, `panas`, `phq9`,
`ptsd_adult`, `vhi10`, `voice_perception`, plus the per-condition `diagnosis/` files.

Ontologies referenced (see each file's `metaData.resources` for the pinned versions):
MONDO, HPO, LOINC, NCIT, NCBITaxon, UCUM, ECO, and the project-local `b2ai:` namespace
for dataset terms that have no ontology equivalent.

## Known gaps in this snapshot

These are properties of the current pipeline, not of the synthetic data:

- **9 conditions emit no `Disease`.** `airway_stenosis`, `benign_lesions`,
  `cognitive_impairment`, `copd_and_asthma`, `glottic_insufficiency`,
  `muscle_tension_dysphonia`, `precancerous_lesions`, `unexplained_chronic_cough`, and
  `unilateral_vocal_fold_paralysis` are still `MONDO:0000000`/`TODO` placeholders in
  `config/voice/diagnosis.yaml`. A participant appearing *only* in one of those files
  gets a phenopacket with no `Disease`.
- **2 tables are not mapped:** `productive_vocabulary`, `psychiatric_history`.
- **4 questionnaire items skipped** (`ptsd_adult.neg_emotional_state=4`, an answer value
  with no entry in the value set).
- Pediatric tables are not ingested in v1.

## Regenerating

Output is deterministic — no timestamps — so a rerun on the same inputs produces an
identical diff-free tree.

```bash
scripts/fetch_synthetic_data.sh      # clones the synthetic repo into data_synth/
uv run b2ai-ingest voice \
  --input data_synth/b2ai-voice-synthetic-phenotype/output/phenotype \
  --output examples/phenopackets/voice-synthetic/
```
