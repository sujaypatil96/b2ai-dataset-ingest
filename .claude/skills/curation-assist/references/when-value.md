# Value conditions — authoring `when_value`

> The `when_value` **grammar** and how the pipeline runs it live in
> `docs/mapping-conventions.md` (and [ADR-0002](../../../docs/adr/0002-conditional-hpo-mapping.md)).
> This file is the **curation heuristic**: when to add a condition, how to pick the cut-point,
> and how to write the present/absent pair. Experts: add worked examples as calls get settled.

A term mapping (`b2ai:phq9.feeling_depressed → HP:0000716 Depression`) says the item is *about*
depression. It does **not** say a participant *has* depression — that depends on the answer. A
`when_value` is the gate that turns an answer into a present/absent `PhenotypicFeature`.

## When to add one (and when not to)

- **Add** a `when_value` when the item is an in-scope sign/symptom whose **answer encodes
  severity/frequency** (an ordinal screener item like PHQ-9/GAD-7, or a checkbox), and a
  present/absent phenotype is the intended output.
- **Leave it empty** when the mapping is only meant to record *aboutness* (a shareable semantic
  link), or when the item is out of scope (admin, score, psychosocial impact, task data — see
  `scope-checklist.md`). An empty `when_value` changes no output; it is always safe.
- **Don't** invent a condition to force a phenotype out of an item that doesn't support one. If
  the answer can't cleanly separate present from absent, say so and leave it semantic-only.

## Picking the cut-point (the part that needs sign-off)

The threshold is a **clinical judgment**, not a lexical one — the validator will not catch a
wrong cut-point. Default reasoning, to be confirmed by a domain expert:

- **Ordinal 0–3 screener items** (PHQ-9, GAD-7: "Not at all / Several days / More than half /
  Nearly every day): the conventional split is **`>=1` present, `==0` absent** — any endorsement
  above "Not at all" asserts the symptom. A stricter clinician may prefer `>=2`; record which and
  why. Do not silently pick one.
- **Checkbox items** ("Checked"/"Unchecked"): `== "Checked"` present, `== "Unchecked"` absent.
- **Only assert the pole you can defend.** If a low answer is genuinely ambiguous (not clearly
  *absent*), author only the present row and omit the absent one — silence is better than a
  wrong `excluded=true`.

Flag the cut-point as **needs expert sign-off** in the review artifact, separately from the
(auto-verified) ontology code.

## Writing the rows

Declare the slot once in the file's SSSOM metadata:

```yaml
# extension_definitions:
#   - slot_name: when_value
#     property: b2ai:when_value
#     type_hint: xsd:string
```

Then the present/absent pair repeats subject/predicate/object and differs only in the last two
columns (it is **not** a duplicate):

```
subject_id                   predicate_id     object_id   predicate_modifier  when_value
b2ai:phq9.feeling_depressed  skos:broadMatch  HP:0000716                      >=1
b2ai:phq9.feeling_depressed  skos:broadMatch  HP:0000716  Not                 ==0
```

- Present row: empty `predicate_modifier`, the "asserts present" condition.
- Absent row: `predicate_modifier: Not` (→ `excluded=true`), the "asserts absent" condition.
- Make the two conditions **mutually exclusive** (`>=1` vs `==0` can't both fire) so one answer
  never yields both present and absent for the same term.
- The `predicate` stays the term-mapping predicate you chose in step 4 (e.g. `broadMatch`); the
  condition rides alongside it, it does not replace it.

## Guardrails

- The validator checks the condition **parses** and `predicate_modifier ∈ {"", "Not"}` — nothing
  more. A green gate is not sign-off on the threshold.
- Numeric conditions are evaluated against the **ordinal score** (the same value the emitted
  Measurement carries), resolved from the data dict's `choices`. If an item has no resolvable
  ordinal, a numeric `when_value` will never fire — use a string/`in {...}` condition instead.
- Every derived feature is auto-stamped with ECO self-report provenance; you do not author that.
