# ADR-0003: Separate answer-interpretation from term mapping

- **Status:** Accepted
- **Date:** 2026-08-24
- **Supersedes:** [ADR-0002](0002-conditional-hpo-mapping.md) decision 3 (the absent pole via
  `predicate_modifier: Not`). ADR-0002's decisions 1, 2, 4, 5 and 6 — `when_value` as an SSSOM
  extension column, execute in the pipeline, ECO:0006160 provenance, a column-preserving parser,
  cut-points are curator judgment — still hold.

## Context

ADR-0002 put the value-gate **inside** the SSSOM mapping files: a `when_value` extension
column carried the cut-point, and the standard `predicate_modifier: Not` marked the absent
pole. A present/absent pair was therefore two rows differing only in those two columns.

A clinical review of the mapping files (Sek Won Kong, Harvard, 2026-08-24) asked for every
absent pole to be removed, and — more fundamentally — for "the concept mapping to be separated
from the interpretation of questionnaire responses." Checking that against the spec and our
own output turned up **two independent defects**, either of which is disqualifying.

**1. `predicate_modifier: Not` does not mean what we used it to mean.** The SSSOM schema's
enum is explicit:

> `Not`: *Negating the mapping predicate. The meaning of the triple becomes subject_id is not
> a predicate_id match to object_id.*
> — `sssom_schema.yaml`, `predicate_modifier_enum`

It negates **the mapping**, not the phenotype. So the shipped pair asserted, in one file, both
that `b2ai:phq9.no_interest` *is* an `skos:exactMatch` to `HP:0012154` and that it *is not* —
a contradiction to any standard SSSOM consumer, and nothing at all about a participant.
ADR-0002 decision 3 called this "phenopackets-native negation"; that was a misreading of the
slot. This alone ends the mechanism, independent of any clinical argument.

**2. The recall window did not survive into the output.** This is the reviewer's own argument
and it was already conceded, unresolved, in `docs/mapping-conventions.md`: nearly every gated
item asks about a bounded period (PHQ-9/GAD-7/LCQ two weeks, PCL-5 one month, ASRS six
months), a `PhenotypicFeature.excluded = true` carries no time scope unless it has an `onset`,
and derived features got no usable `TimeElement` because Bridge2AI-Voice session ids are
opaque hashes. "Not at all *in the past two weeks*" was therefore published as unqualified
lifetime absence. On the synthetic tree that was **112 such assertions**.

Note what the two defects do *not* implicate. Both are about the **absent** pole: one says the
slot used to mark it means something else, the other says the claim it makes is unbounded.
Neither says anything about `when_value` on a *present* pole, which asserts only that a mapping
applies at certain answers — no negation, nothing about a participant, nothing needing a window.

What was actually missing was a home for the things a mapping row genuinely cannot hold: the
instrument's **recall window**, which is a property of the instrument rather than of any one
mapping and which no SSSOM slot carries; and the absent pole itself, which — once
`predicate_modifier` goes — has no legal SSSOM expression at all.

## Decision

**Split the layers along what SSSOM can express. Keep the curation. Gate absence on being scopable.**

The split is not "mapping here, interpretation there" — it is drawn where the spec draws it.

1. **The present pole stays in the SSSOM row, as `when_value`.** It qualifies *which answers make
   the mapping applicable* — "this item is about `HP:0012154` at answers `>= 1`" — which is still
   a statement about the item, creates no contradiction, and reads better beside the mapping it
   qualifies. ADR-0002 already verified the column is spec-compliant (`sssom-py` validates it) and
   backward-compatible (an SSSOM-core consumer ignores it and still gets the mapping). Neither
   defect above touches it, and removing it would separate the condition from the mapping it
   modifies for no benefit — the reason ADR-0002 rejected a sidecar in the first place.

2. **`predicate_modifier` is removed outright, and that forces the absent pole out.** It was the
   only slot marking a row as the absent pole, so once it goes there is *no* legal SSSOM
   expression for absence left. The derivation layer therefore has to exist regardless of taste.
   `sssom_validate.py` now rejects the column (`interpretation-in-mapping`) rather than ignoring
   it, so the misuse cannot return by accident. With the pole gone, a repeated
   `(subject, predicate, object)` is once again simply a duplicate.

3. **Absent poles move to `mappings/derivations/<instrument>.yaml`, one file per instrument** —
   which is also the only place the thing that *bounds* an exclusion can live. Each file carries
   the `recall_window` (machine-readable ISO-8601 duration plus its provenance: `data_dict`,
   `published_instrument`, or `unverified`), the `scoring_reference` behind both poles'
   cut-points, and any `open_question` about them. A pole may instead be declared `unauthorable`
   with a reason from a closed set (`conflated-superset`, `conflated-sense`, `baseline-relative`,
   `intensity-qualified`), so a curator's decision *not* to derive is recorded rather than showing
   up as a silent gap. All 26 absent poles migrated; the 36 present poles never moved.

4. **A derivation may not invent a mapping.** `validate-mappings` checks both layers and fails if
   a rule's `(subject_id, object_id)` pair has no row in the mapping set (`unanchored-rule`). The
   rule file also may not carry a `present` block (`present-in-rule-file`), and a table with gated
   mappings but no instrument file warns (`no-instrument-file`) — its features would carry no
   scope. These checks are what keep the split from becoming drift.

5. **The absent pole is authored but gated on being scopable.** `hpo_rules.scoped_onset` resolves
   the recall window against a session's observation time into `[observation − window,
   observation]`, and the feature is skipped when that returns `None`. `TimePoint` gained
   `interval_start`/`interval_end`; the emitter renders them as a GA4GH `TimeElement.interval`,
   ranked above a bare timestamp because a bounded period is the stronger claim.

   Bridge2AI-Voice 3.1.0 session ids carry no timestamp, so today this resolves for no session
   and **no `excluded` feature is emitted** — the guarantee the review asked for. Skips are
   counted (`absent_features_unscoped`) and printed in the ingest summary, never dropped
   silently. The synthetic run goes from 222 derived features (112 of them excluded) to 110, with
   "absent poles withheld: 112" on the summary, and every remaining feature identical to before.

   This is deliberately a *data* blocker, not a policy flag. When session timestamps arrive,
   absence becomes representable — correctly scoped — with no re-curation and no code change.

## Consequences

- The mapping sets are shareable as what they claim to be: no contradiction, and no assertion of
  absence that the data cannot support. A consumer that ignores `when_value` still gets every
  mapping; one that reads it gets the present-pole gate too.
- Questions about interpretation now have a place to live that is not a mapping row. The first
  beneficiary is already recorded: the same review objected that one ASRS item at "Often" cannot
  establish impulsivity, since the ASRS scores Part A as 4-of-6. That is an argument about the
  derivation, so `adhd_adult.yaml` carries it as an `open_question` while
  `b2ai:adhd_adult.interrupt_others -> HP:0100710` stands untouched.
- Output changes by exactly 112 assertions, all of them `excluded`. Every present feature is
  unchanged. Present poles are deliberately *not* gated on scoping — presence is existential over
  the window ("had this on several days in a fortnight" is a defensible positive claim), absence
  is universal over a life.
- Rules now load from two files, so the loader reads both and stamps present poles with the
  window from their instrument file. Emitted feature order is sorted by `(pole, object_id)` rather
  than left to file order, so moving a row between files cannot silently reshuffle output.
- A malformed SSSOM metadata header would disable every present pole in that file while the run
  still looked green. The loader now warns on an unreadable mapping set, and a test pins it.
- The `unverified` window on the Dyspnea Index is explicit data rather than a footnote. It means
  *unknown*, never *unbounded*; its absent poles stay unemittable for the same reason the bounded
  instruments' do.

## Alternatives considered

- **Just delete the 26 absent rows** (the literal ask). Rejected: it discards real curation and
  leaves the recall window with nowhere to live, which is what makes absence permanently
  unrepresentable rather than merely blocked on data.
- **Also move `when_value` out of the mapping sets**, taking the reviewer's "separate the concept
  mapping from the interpretation of questionnaire responses" at its widest. This is what the
  first draft of this ADR did, and it was rejected on review of the ADR itself. Neither defect
  above implicates `when_value`: the recall-window argument is about the *absent* pole, and the
  contradiction is about `predicate_modifier`. Removing it on the strength of the principle alone
  would re-litigate ADR-0002 decision 1 without new evidence, and would split a rule across two
  files for no gain in either correctness or shareability.
- **Keep the poles, add a policy flag to suppress `excluded`.** Rejected: a hand-set flag
  claims the problem is a preference. It is not — it is that we cannot say *when* the absence
  held. Deriving the gate from whether an interval is computable states the real precondition
  and lifts itself when the precondition is met.
- **Scope absence with `PhenotypicFeature.modifiers` or free-text `description`.** Rejected:
  no ontology term denotes "over the past two weeks", and free text is not machine-readable.
  `TimeElement.interval` is the schema's own answer.
- **A single sidecar for all instruments.** Rejected: recall window, scoring reference, and
  cut-point convention are *per-instrument* properties, and the per-instrument file makes the
  join to the data table (`instrument` == data-dict stem == the `<table>` in
  `b2ai:<table>.<column>`) checkable.
- **Reify value-qualified subjects** (`…no_interest.present` → `HP:0012154`). Still rejected,
  for ADR-0002's reason: it puts the interpretation back in the mapping set, just spelled
  differently.
