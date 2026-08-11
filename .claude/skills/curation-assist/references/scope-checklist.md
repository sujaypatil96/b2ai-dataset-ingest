# Scope checklist — is this column in scope for an ontology mapping?

> **Domain experts: edit this file.** It is the shared, reviewable rulebook for *which*
> columns get mapped. When a scope call is contested, resolve it here (with an example) so the
> next run is consistent. This is the single biggest lever on curation reproducibility.

Apply against the column's data-dictionary **`description`**, not its name. Target ontology is
HPO (phenotypic abnormalities); MONDO (diseases) and LOINC (assays) have their own scope.

## DO map (in scope)

- **Clinical signs / symptoms / findings** — a phenotypic abnormality the participant *has* or
  *reports*. Examples: `dizziness`, `ataxia`, `shortness_breath`, `hoarse voice`, PHQ-9
  `no_interest` (anhedonia), GAD-7 `nervous_anxious` (anxiety), Parkinson's gold-standard
  `bradykinesia`/`rigidity`/`tremor`.
- **A questionnaire item whose content *is* a phenotype**, even if worded as self-report
  ("Feeling down, depressed, or hopeless" → HP:5200273 *Pathological sadness*). Map the
  phenotype at the **item's** granularity, not the syndrome the instrument screens for — see
  the granularity trap in `predicate-rules.md`. Predicate: see `predicate-rules.md`.

## DON'T map (out of scope) — record the bucket and move on

| Bucket | Tell-tale | Examples |
| --- | --- | --- |
| **Admin** | identifiers, timing | `participant_id`, `*_session_id`, `*_duration` |
| **Score / total** | precomputed sum | `vhi_10_calc_score` (a measurement, handled elsewhere) |
| **Psychosocial / QoL impact** | how the problem *affects life/feelings* | "restrict my social life", "made me feel embarrassed", "hard to do your work", most of LCQ and VHI-10 |
| **Trigger / modifier** | what makes it better/worse | "worse with stress", "weather changes", "exposure to paint" |
| **Task performance / stimulus** | test items, not symptoms | all of `productive_vocabulary`, `*_acoustic_task_id` |
| **History / utilization** | past care, not current state | "ever prescribed medication", "ever saw a mental-health professional" |
| **Positive-affect adjective** | not an abnormality | PANAS `active/alert/inspired`, custom-affect `joyful/energetic/motivated` |
| **Redundant facet** | same phenotype already captured by a sibling item | GAD-7 `worry_too_much`/`cant_control_worry` when `nervous_anxious`→Anxiety is already mapped; ASRS's 9 inattention items → one *Short attention span* |
| **Bidirectional / no clean term** | "X **or** its opposite" with no single HPO node | PHQ-9 `move_speak_slow` ("slow **or** restless") |
| **Treatment / procedure / device / medication** | an *intervention*, not a phenotype | confounders `chemotherapy`, `botox_injections`, `deep_brain_stimulator`, `antidepressants`, `tonsillectomy`, `supplemental_oxygen` |
| **Substance / lifestyle** | consumption/behaviour, not a sign | `alcohol_freq`, `cocaine`, `caffeine_intake`, `nicotine_*` |
| **Injury / trauma** | acute event, not an HPO phenotype | confounders `chest_wall_trauma`, `craniofacial_trauma`, `traumatic_brain_injury` |
| **`[DEPRECATED]` / generic catch-all** | dead column or non-specific | any `[DEPRECATED]` label; "any **other** X condition", `medication` (bare) |

## Grey areas — flag for expert decision, don't auto-decide

- **Somatic items inside a psych scale** (e.g. DSM-5 `unexplained_aches`, `memory_issues`):
  usually mappable (Pain, Memory impairment) — confirm the term fits.
- **Cough/voice QoL items that name a real sign** (LCQ `lcq_sleep` cough-disturbed sleep,
  `lcq_tired`): the *impact* is out of scope, but a co-named sign may be in scope — decide
  per item.
- **Instrument-level mapping** (map the whole scale to one phenotype, e.g. VHI-10 → Dysphonia,
  like `voice_perception`): allowed when item-level mapping would be redundant/psychosocial.
  Record it as an instrument-level mapping with a comment.

## REDCap checkbox export columns (`col___value`) — map the concept once, not the encoding

Wide tables expand multi-choice fields into `col___value` columns. Which one carries the
*concept* depends on the field type:

- **Single-choice history field** (e.g. confounders `acid_reflux` with choices
  past/current/never/no_answer, expanded to `acid_reflux___current`, `___past`, …): the **base**
  column (`acid_reflux`) is the concept — map that once. The `___current/past/never` columns are
  *value encodings* of the same item; mapping each would map the same HPO term 4× (a value gate,
  not a term mapping — that's `when_value`'s job).
- **Multi-select checkbox group** (e.g. `peds_mc_breathing_conditions` with options
  asthma/bronchiolitis/…): the base column is just the group header; each **`___option`** column
  is a *distinct condition* — map the options (`…___asthma` → Asthma, `…___bronchiolitis` →
  Bronchiolitis), not the header.

Tell them apart by the base column's choices: a past/current/never (or yes/no) base = single-choice
→ map base; a base whose "choices" are the option list = checkbox group → map the options.

## Disease terms → best-fit HPO phenotype, or leave for MONDO

HPO is a *phenotype* ontology, but medical-history checklists list many **diseases**. Convention
(confirmed for this project): map each disease to its **best-fit HPO phenotype** — `exactMatch`
where HPO has the term (Asthma, Bipolar affective disorder, Schizophrenia), `broadMatch` to the
disorder's core phenotype otherwise (`anxiety_disorder`→Anxiety, `panic_disorder`→Panic attack,
`epilepsy`→Seizure). **Skip** (record as out-of-scope, → future MONDO layer) when no defensible HPO
phenotype exists: cystic fibrosis, multiple sclerosis, COVID-19, tuberculosis, Sjögren's, trisomy 21,
osteogenesis imperfecta. Don't force a generic parent (e.g. don't map *congenital heart disease* to
*Abnormal heart morphology*) just to avoid a skip.

## Momentary-state affect scales (PANAS, custom affect) → relatedMatch

An item that rates *how you feel right now* (a 1–5 / 0–10 state rating) is not an assertion of a
persistent clinical sign. Map only the negative items that name a real phenotype (`nervous`→Anxiety,
`lack_of_pleasure`→Anhedonia, `agitated`→Agitation) as **`relatedMatch`** with a "momentary-state"
comment; skip positive-affect items entirely. Contrast with a screener (PHQ-9/GAD-7) whose items
*are* symptoms.

## Coverage discipline

When a table is only partially mapped, **say what was skipped and why** (bucket counts) — a
silent "done" reads as "fully covered" when it isn't. (This is exactly how a gap in the
questionnaire coverage went unnoticed until audited.)
