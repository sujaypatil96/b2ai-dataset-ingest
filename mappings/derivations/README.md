# Instrument rule files

**These files are not mappings, and they are not the whole interpretation layer either.**

How an answer becomes a `PhenotypicFeature` is split across two files, along the line the SSSOM
spec draws:

| | Where it lives | Why there |
| --- | --- | --- |
| **Present pole** | the SSSOM row's `when_value` column | it qualifies *which answers make the mapping applicable* — still a statement about the item, and it belongs beside the mapping it qualifies |
| **Absent pole** | `absent:` in these files | it has no legal SSSOM expression: `predicate_modifier: Not` negates *the mapping*, not the phenotype |
| **Recall window** | `recall_window:` in these files | a property of the *instrument*, not of any one mapping — and no SSSOM slot carries it |
| **Scoring reference, open questions** | these files | per-instrument, and they justify *both* poles' cut-points |

See [ADR-0003](../../docs/adr/0003-separate-derivation-from-mapping.md). The split came out of a
clinical review (Sek Won Kong, Harvard, 2026-08-24).

## Shape

```yaml
instrument: phq9                  # data-dict file stem; matches b2ai:<instrument>.<column>
label: Patient Health Questionnaire-9 (PHQ-9)
recall_window:
  iso8601: P2W                    # null when the instrument has no verified window
  text: over the last 2 weeks
  source: data_dict               # data_dict | published_instrument | unverified
scoring_reference: >-             # where the cut-points come from, so they can be checked
  ...
rules:
  - subject_id: b2ai:phq9.no_interest
    object_id: HP:0012154
    object_label: Anhedonia
    confidence: 0.95
    absent:
      when_value: "==0"
      note: "'Not at all'"
```

A `present:` block here is an error — the validator rejects it and the loader ignores it.

The absent pole may instead be `unauthorable:` with a reason code, which records a curator
decision *not* to author it (and why) rather than leaving a silent gap:

| code | meaning |
| --- | --- |
| `conflated-superset` | the object subsumes more than the item asks about, so the item's floor cannot exclude it |
| `conflated-sense` | the item conflates two senses; an endorsement cannot say which was meant |
| `baseline-relative` | the item is phrased "more than usual", so 0 means *not worse*, not *absent* |
| `intensity-qualified` | the item's floor denies an escalation, not the phenotype |

## Every `subject_id` must also exist in the SSSOM files

A rule cannot invent a mapping. `b2ai-ingest validate-mappings` enforces that each rule's
`subject_id`/`object_id` pair is present in `mappings/*.sssom.tsv`, and warns when a table has
gated mappings but no rule file here (its features would carry no recall window).

## The absent pole is authored but gated

`PhenotypicFeature.excluded = true` carries no time scope of its own, so an absent pole derived
from "not at all **in the past two weeks**" would publish as unqualified lifetime absence. Absent
rules are therefore emitted **only** when the recall window resolves against a session timestamp
into a concrete interval. Bridge2AI-Voice 3.1.0 session ids are opaque hashes with no timestamp,
so today that resolves for no session and **no absent feature is emitted**. The curation is kept
here, correctly conditioned, so that absence becomes representable the moment session timestamps
exist — with no re-curation.
