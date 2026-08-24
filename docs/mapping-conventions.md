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
term-to-term artifact: a row says the item is *about* the HPO concept, and nothing more. It
never asserts that a participant *has* it — that depends on the answer, and is a separate,
weaker, instrument-specific claim that lives in `mappings/derivations/*.yaml` (see
"Deriving features from answers" below and
[ADR-0003](adr/0003-separate-derivation-from-mapping.md)).

**The two layers are deliberately not the same file.** A mapping holds for everyone, forever,
independent of any instrument; an interpretation is contingent on the instrument's scale,
scoring rule and recall window. They were fused until 2026-08-24, when a clinical review asked
that they be separated — see the ADR for the two defects that made the fusion untenable.

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

### Deriving features from answers

A term→term mapping records that an item is *about* an HPO concept; it does not assert a
participant *has* it. That step lives in **`mappings/derivations/<instrument>.yaml`**, one file
per instrument, keyed by the same `b2ai:<table>.<column>` subject id. See
[`mappings/derivations/README.md`](../mappings/derivations/README.md) for the file shape and
[ADR-0003](adr/0003-separate-derivation-from-mapping.md) for why it is a separate layer.

Each rule names a `subject_id`/`object_id` pair and gives up to two poles:

- **`when_value`** — a condition on the participant's answer. Grammar: comparisons `>=1`, `<=3`,
  `>0`, `<2`, `==0`, `!=0`; string equality `== "Checked"`; membership `in {1,2,3}` /
  `in {"a","b"}`; and `&` conjunction (`>=1 & <=3`). Numeric conditions are evaluated against the
  same **ordinal score** the emitted Measurement carries (resolved from the data dict's
  `choices`); string conditions against the raw cell (case-insensitively).
- **`unauthorable`** — instead of a condition: a recorded decision *not* to derive this pole,
  with a reason from the closed set (`conflated-superset`, `conflated-sense`,
  `baseline-relative`, `intensity-qualified`) and a `note` saying why. A declined pole is
  explicit; a missing one is a gap.

The instrument's **`recall_window`** and **`scoring_reference`** sit at the top of the file,
because they are properties of the instrument, not of any one item.

**A derivation may not invent a mapping.** Every rule's `(subject_id, object_id)` pair must
exist as a row in `mappings/*.sssom.tsv`; `b2ai-ingest validate-mappings` fails with
`unanchored-rule` otherwise. That check is what stops the two layers from drifting apart.
The validator also rejects `when_value`/`predicate_modifier` *inside* a mapping set
(`interpretation-in-mapping`), so the fusion cannot come back by accident.

#### Choosing a cut-point

Two things bear on a `when_value`, and they are not the same:

1. **The instrument's own scoring rule** — what its designers count as a positive endorsement
   (e.g. the ASRS scores its Part A hyperactivity items positive only at *Often*/*Very Often*).
   Cite it in the file's `scoring_reference` so it can be checked rather than trusted.
2. **What the HPO term itself requires** — `HP:5200273` *Pathological sadness* is defined as
   sadness "excessive in intensity, duration, or resistance to self-regulation", which a single
   rare day does not meet whatever the instrument says.

They usually agree. **Where they conflict, weight (2)**: the assertion being emitted is about the
HPO term, not about the questionnaire.

**Compare answer labels, never the integers.** Two instruments can gate the same HPO term at the
same *severity* while using different numbers, because their scales differ in length and in kind.
`HP:0012154` *Anhedonia* is gated three ways:

| Item | Scale | Cut-point | Answer it fires at |
| --- | --- | --- | --- |
| `phq9.no_interest` | frequency, 0–3 | `>=1` | "Several days" |
| `dsm5_adult.little_interest` | frequency, 0–4 | `>=2` | "Mild (**Several days**)" |
| `ptsd_adult.losing_interest` | **severity**, 0–4 | `>=2` | "Moderately" |

The first two are the same severity at different integers — `dsm5_adult` has an extra rung at the
bottom ("Slight — rare, less than a day or two"), so its 2 is phq9's 1. Setting both to `>=1`
looks like harmonization and is the opposite: it drops the DSM-5 bar to "rare, less than a day or
two" while leaving PHQ-9 at "several days".

The third cannot be aligned with either: PCL-5 rates *severity*, not frequency, and no answer on
that scale is equivalent to "several days".

**This is a curator judgment, not a machine check.** An earlier automated test required every
instrument gating a term to share one `when_value` string; it was removed because that premise is
false in both directions — equal integers are not equal severities, and non-commensurable scales
(frequency vs severity) have no equal labels to compare.

**A single item is not a construct.** Where an instrument scores a construct from several items
(ASRS Part A is 4-of-6), a one-item rule overstates what the instrument supports. That objection
belongs in the derivation file — `adhd_adult.yaml` carries it as an `open_question` — not in the
term mapping, which is unaffected either way.

#### The absent pole, and why nothing is emitted today

`excluded = true` is a strong claim, and an **unqualified** one: a phenopacket carries no time
scope on an excluded feature unless it has an `onset`. Emitted from a two-week item, it does not
say "absent over the last fortnight" — it says the participant does not have the phenotype.

Two independent gates therefore apply.

**Gate 1 — is the pole authorable at all?** Only if the item's lowest answer denies the
phenotype rather than something narrower. Three ways that fails, each a reason code:

- **`baseline-relative`.** "Feeling more irritated… *than usual*" — a participant who is always
  irritable answers `0`, which means *not worse than usual*, not *not irritable*.
- **`intensity-qualified`.** "Being extremely irritable *to the point where you yelled, got into
  fights, or destroyed things*" — `0` denies the escalation, not the emotion.
- **`conflated-superset`.** A `broadMatch` object subsumes more than the item asks about, so a
  `0` cannot exclude it (a PHQ-9 sleep `0` rules out insomnia and hypersomnia, not sleep apnea).

A **conflated** "A or B" item is not a failure on its own: `0` denies both senses, so an absent
pole is admissible even where the *present* pole cannot be attributed to one sense (see
`phq9.feeling_bad_self`, whose present pole is `unauthorable: conflated-sense` while its absent
pole is authored).

**Gate 2 — can the assertion be bounded?** Nearly every item asks about a fixed period, so `0`
means *not during that window*:

| Instrument | Window in the data dict | Published instrument | `source` |
| --- | --- | --- | --- |
| PHQ-9, GAD-7, Leicester Cough | two weeks | two weeks | `data_dict` |
| DSM-5 adult | only on `little_interest` | two weeks | `published_instrument` |
| ASRS (`adhd_adult`) | none | past 6 months | `published_instrument` |
| PCL-5 (`ptsd_adult`) | none | past month | `published_instrument` |
| Dyspnea Index | none | none found | `unverified` |

**The data dict is not authoritative here.** Three instruments record no window, but ASRS and
PCL-5 are bounded in their published form, so the omission is a gap in the dict rather than a
property of the instrument. Never infer that an item is unbounded from the dict's silence — and
note that `unverified` means *unknown*, not *unbounded*.

So `hpo_rules.scoped_onset` turns the window into a concrete interval —
`[observation − window, observation]` — and an absent feature is emitted **only** when that
succeeds. It needs both a known window and a session observation time. Bridge2AI-Voice 3.1.0
session ids are opaque hashes with no timestamp, so today it succeeds for no session and **no
`excluded` feature is emitted at all**. Skips are counted as `absent_features_unscoped` and
printed in the ingest summary ("absent poles withheld: N"), never dropped silently.

This is a *data* blocker, not a policy choice. The curation stays in the files, correctly
conditioned; the moment session timestamps exist, absence becomes representable — as a GA4GH
`TimeElement.interval` on the feature's `onset` — with no re-curation and no code change.
`tests/test_hpo_rules.py::test_absent_pole_is_emitted_once_the_window_can_be_scoped` pins that
path.

Present poles are deliberately **not** gated this way. Presence is existential over the window
("had this on several days in a fortnight" is a defensible positive claim); absence is universal
over a life.

#### Provenance on every derived feature

Each derived feature is stamped with a human-readable `description` (source item, instrument,
pole, cut-point, recall window, confidence) and a GA4GH `Evidence` whose `evidenceCode` is
`ECO:0006160` ("self-reported patient statement … in automatic assertion") with an
`ExternalReference` back to the source item — self-report-derived phenotypes stay
distinguishable from clinician-observed findings.

The validator checks that `when_value` **parses**, that a pole declares exactly one of
`when_value`/`unauthorable`, and that reasons and windows come from their closed sets; whether a
cut-point is *clinically* right is a curator judgment (see the `curation-assist` skill). The
apply path lives in `mapping/derivations.py` (rule model + loader), `mapping/hpo_rules.py`
(scoping + derivation) and `mapping/conditions.py` (the grammar); the reader runs it during
questionnaire ingestion.
