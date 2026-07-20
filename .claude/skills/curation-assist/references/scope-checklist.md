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
  ("Feeling down, depressed, or hopeless" → Depression). Map the phenotype; see
  `predicate-rules.md` for the predicate.

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
| **Redundant facet** | same phenotype already captured by a sibling item | GAD-7 `worry_too_much`/`cant_control_worry` when `nervous_anxious`→Anxiety is already mapped |
| **Bidirectional / no clean term** | "X **or** its opposite" with no single HPO node | PHQ-9 `move_speak_slow` ("slow **or** restless") |

## Grey areas — flag for expert decision, don't auto-decide

- **Somatic items inside a psych scale** (e.g. DSM-5 `unexplained_aches`, `memory_issues`):
  usually mappable (Pain, Memory impairment) — confirm the term fits.
- **Cough/voice QoL items that name a real sign** (LCQ `lcq_sleep` cough-disturbed sleep,
  `lcq_tired`): the *impact* is out of scope, but a co-named sign may be in scope — decide
  per item.
- **Instrument-level mapping** (map the whole scale to one phenotype, e.g. VHI-10 → Dysphonia,
  like `voice_perception`): allowed when item-level mapping would be redundant/psychosocial.
  Record it as an instrument-level mapping with a comment.

## Coverage discipline

When a table is only partially mapped, **say what was skipped and why** (bucket counts) — a
silent "done" reads as "fully covered" when it isn't. (This is exactly how a gap in the
questionnaire coverage went unnoticed until audited.)
