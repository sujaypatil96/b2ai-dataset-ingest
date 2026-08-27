# Value conditions — authoring `when_value`

> The `when_value` **grammar** and how the pipeline runs it live in
> `docs/mapping-conventions.md` (and
> [ADR-0003](../../../docs/adr/0003-separate-derivation-from-mapping.md)).
> This file is the **curation heuristic**: when to add a condition, how to pick the cut-point,
> and how to write the poles. Experts: add worked examples as calls get settled.

A term mapping (`b2ai:phq9.feeling_depressed → HP:5200273 Pathological sadness`) says the item is
*about* that phenotype. It does **not** say a participant *has* it — that depends on the answer. A
`when_value` is the gate that turns an answer into a present/absent `PhenotypicFeature`.

**The two poles live in different files.** The **present** pole is the SSSOM row's own
`when_value` column, beside the mapping it qualifies. The **absent** pole is in
`mappings/derivations/<instrument>.yaml`, because since ADR-0003 it has no legal SSSOM
expression — `predicate_modifier` is rejected there — and because bounding it needs that file's
`recall_window`. An absent rule must be *anchored*: its `subject_id`/`object_id` pair has to
exist as a mapping row, so author the mapping first.

## When to add one (and when not to)

- **Add** a `when_value` when the item is an in-scope sign/symptom whose **answer encodes
  severity/frequency** (an ordinal screener item like PHQ-9/GAD-7, or a checkbox), and a
  present/absent phenotype is the intended output.
- **Leave `when_value` empty** when the mapping is only meant to record *aboutness* (a
  shareable semantic link), or when the item is out of scope (admin, score, psychosocial impact,
  task data — see `scope-checklist.md`). An empty `when_value` changes no output; it is always
  safe. Say in the `comment` why there is no gate, if the reason is not obvious.
- **Declare a pole `unauthorable`** when you considered it and decided against it, with a
  reason from the closed set (`conflated-superset`, `conflated-sense`, `baseline-relative`,
  `intensity-qualified`) and a `note`. A declined pole is a recorded decision; a silently
  missing one is a gap nobody can audit.
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

### The absent pole is emitted only if it can be bounded

`excluded = true` carries no time scope of its own, so an absent pole derived from "not at all
*in the past two weeks*" would publish as unqualified lifetime absence. The pipeline therefore
emits an absent feature only when the instrument's `recall_window` can be resolved against a
session observation time into a concrete interval. Bridge2AI-Voice session ids carry no
timestamp, so **today no `excluded` feature is emitted at all** — the skips are counted, not
hidden.

Author the absent pole anyway when it is justified. The curation is kept, correctly
conditioned, and starts emitting the moment session timestamps exist. What you must get right
is the instrument's `recall_window` — `iso8601` plus an honest `source` (`data_dict`,
`published_instrument`, `unverified`). `unverified` means *unknown*, never *unbounded*.

## Writing it

The present pole rides on the mapping row:

```
subject_id                   predicate_id     object_id   ...  comment  when_value
b2ai:phq9.feeling_depressed  skos:exactMatch  HP:5200273  ...           >=1
```

with the slot declared once in the file's SSSOM metadata:

```yaml
# extension_definitions:
#   - slot_name: when_value
#     property: b2ai:when_value
#     type_hint: xsd:string
```

The absent pole goes in the instrument file, named for the data-dict stem:

```yaml
# mappings/derivations/phq9.yaml
instrument: phq9
label: Patient Health Questionnaire-9 (PHQ-9)
recall_window: { iso8601: P2W, text: over the last 2 weeks, source: data_dict }
scoring_reference: >-
  Kroenke K, Spitzer RL, Williams JBW. J Gen Intern Med. 2001;16(9):606-613.
rules:
  - subject_id: b2ai:phq9.feeling_depressed
    object_id: HP:5200273
    object_label: Pathological sadness
    confidence: 0.95
    absent:
      when_value: "==0"
      note: "'Not at all'"
```

- Make the two conditions **mutually exclusive** (`>=1` vs `==0` can't both fire) so one answer
  never yields both present and absent for the same term.
- A `present:` block in the instrument file is an error — that pole belongs on the row.
- Per the table above, a `broadMatch` object usually gets a present `when_value` with
  `absent: {unauthorable: conflated-superset}`, and a `narrowMatch` object the reverse.
- Put the cut-point's justification in `scoring_reference` so a reviewer can check it rather
  than take it on trust.

## Guardrails

- The validator checks the condition **parses** (in either file), that the absent pole declares
  exactly one of `when_value`/`unauthorable`, and that the rule is anchored to a mapping row —
  nothing more. A green gate is not sign-off on the threshold.
- Numeric conditions are evaluated against the **ordinal score** (the same value the emitted
  Measurement carries), resolved from the data dict's `choices`. If an item has no resolvable
  ordinal, a numeric `when_value` will never fire — use a string/`in {...}` condition instead.
- Every derived feature is auto-stamped with ECO self-report provenance; you do not author that.
