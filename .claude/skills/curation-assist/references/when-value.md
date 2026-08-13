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

## The predicate decides *which poles* you may assert

"Only assert the pole you can defend" is not a case-by-case feel — for a hierarchical predicate
it follows from the direction you already chose in `predicate-rules.md`. Endorsement travels
**up** the hierarchy; denial travels **down**.

| Predicate | Present (`>=1`) | Absent (`==0`) | Why |
| --- | --- | --- | --- |
| `exactMatch` | ✅ | ✅ | item ≡ phenotype, so both directions carry |
| `broadMatch` (object broader) | ✅ | ❌ | denying the specific item cannot exclude the umbrella — the participant may have it via another child |
| `narrowMatch` (object narrower) | ❌ | ✅ | endorsing the broad item cannot say *which* narrow sense; denying it denies all of them |
| `relatedMatch` | ❌ | ❌ | only partial overlap — neither direction is sound; leave ungated |

Worked examples from the GAD-7/PHQ-9 pass:

- `phq9.trouble_sleeping` → HP:0002360 *Sleep disturbance* (broad). "Not at all" rules out
  insomnia and hypersomnia but not sleep apnea or a parasomnia, both children of the same term —
  so present-only.
- `phq9.feeling_bad_self` → HP:0031469 *Low self-esteem* + HP:6000011 *Guilt* (narrow ×2).
  A `>=1` answer cannot say which half of the conflated item was endorsed, so asserting either
  would be a coin flip; a `==0` answer denies both — so absent-only, on both rows.
- `vhi10.strain_voice` → HP:0001618 *Dysphonia* (related). Left ungated: HPO has no term for
  effortful phonation (searched "strained voice", "vocal strain", "vocal fatigue", "phonation",
  "effortful speech" — no hits), and a relatedMatch cannot carry either pole.

**A conflation-retarget `broadMatch` is still a `broadMatch`.** `no_appetite` → *Abnormal eating
behavior* was retargeted so the term subsumes *both* poles of the item, which makes the present
pole sound; it does not make the absent pole sound, because the term keeps its other children.

**Consequence: the predicate is now load-bearing for output.** Before this, a wrong
`broad`/`narrow` direction was a metadata blemish; now it decides whether a participant's
phenopacket says "present" or "excluded". When authoring a gate, re-read the object's definition
and confirm the direction before trusting it — `gad7_anxiety.afraid_of_things` → HP:0033845
*Sense of impending doom* is labelled `broadMatch`, but its own `comment` argues the HPO term is
*stronger* than the item ("life-threatening or tragic" vs "something awful"), which is the
narrow direction. That row is held ungated until the direction is settled.

### Absent-only rows: keep the semantic row, add the `Not` row

For an absent-only gate, do **not** simply put `predicate_modifier: Not` on the existing row.
`predicate_modifier` is SSSOM-core, and an SSSOM-core consumer drops `when_value` — so a lone
negated row reads as "this mapping does *not* hold" and the semantic mapping is lost. Leave the
ungated row in place and add the `Not`/`==0` row beside it, the same shape as a present/absent
pair (the validator's duplicate key includes both columns, so this is not a duplicate).

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
