# ADR-0003: Separate answer-interpretation from term mapping

- **Status:** Accepted
- **Date:** 2026-08-24
- **Supersedes:** [ADR-0002](0002-conditional-hpo-mapping.md) decisions 1 and 3 (the
  `when_value` extension column and the `predicate_modifier: Not` absent pole). ADR-0002's
  decisions 2, 4, 5 and 6 — execute in the pipeline, ECO:0006160 provenance, a
  column-preserving parser, cut-points are curator judgment — still hold.

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

Underneath both defects is one structural mistake: a term mapping and an answer
interpretation are different claims with different truth conditions, and they were sharing a
row. The mapping (`this item is about anhedonia`) holds for everyone, forever, independent of
any instrument. The interpretation (`answering "several days" warrants asserting anhedonia,
for the last two weeks`) is contingent on the instrument, its scale, its scoring rule, and its
recall window. Fusing them meant the mapping file could not be shared without shipping our
interpretation, and the interpretation had nowhere to record the window that qualifies it.

## Decision

**Split the layers. Keep the curation. Gate absence on being scopable.**

1. **`mappings/*.sssom.tsv` become pure term-to-term mapping sets.** The `when_value` and
   `predicate_modifier` columns are removed, along with the `extension_definitions` metadata
   that declared them. A present/absent pair collapses to the single row it always was
   semantically. The questionnaire set goes from 97 rows to 71; **no term mapping is lost** —
   the four subjects whose only gated rows were absent poles keep their mapping rows.
   `sssom_validate.py` now *rejects* both columns (`interpretation-in-mapping`) rather than
   ignoring them, so the fusion cannot be reintroduced by accident.

2. **Interpretation moves to `mappings/derivations/*.yaml`, one file per instrument.** Each
   file carries what a mapping row never could: the instrument's `recall_window` (as a
   machine-readable ISO-8601 duration plus its provenance — `data_dict`,
   `published_instrument`, or `unverified`), a `scoring_reference` for where the cut-points
   come from, and per-rule `present`/`absent` poles. A pole may instead be declared
   `unauthorable` with a reason from a closed set (`conflated-superset`, `conflated-sense`,
   `baseline-relative`, `intensity-qualified`), so a curator's decision *not* to derive is
   recorded rather than showing up as a silent gap. All 62 previously-gated poles migrated
   without loss.

3. **A derivation may not invent a mapping.** `validate-mappings` now checks both layers and
   fails if a rule's `(subject_id, object_id)` pair has no row in the mapping set
   (`unanchored-rule`). This is what keeps the split from becoming drift.

4. **The absent pole is authored but gated on being scopable.** `excluded = true` is emitted
   only when the instrument's recall window can be resolved against a session's observation
   time into a concrete interval — `hpo_rules.scoped_onset` returns
   `[observation − window, observation]`, and the feature is skipped when it returns `None`.
   `TimePoint` gained `interval_start`/`interval_end`; the emitter renders them as a GA4GH
   `TimeElement.interval`, ranked above a bare timestamp because a bounded period is the
   stronger claim.

   Bridge2AI-Voice 3.1.0 session ids carry no timestamp, so today this resolves for no session
   and **no `excluded` feature is emitted** — the guarantee the review asked for. Skips are
   counted (`absent_features_unscoped`) and printed in the ingest summary, never dropped
   silently. The synthetic run goes from 222 derived features (112 of them excluded) to 110,
   with "absent poles withheld: 112" on the summary.

   This is deliberately a *data* blocker, not a policy flag. When session timestamps arrive,
   absence becomes representable — correctly scoped — with no re-curation and no code change.

## Consequences

- The mapping sets are now shareable as what they claim to be. A downstream consumer gets our
  HPO mappings without inheriting our cut-points, our recall-window assumptions, or a
  contradiction.
- Questions about interpretation now have a place to live that is not the term mapping. The
  first beneficiary is already recorded: the same review objected that one ASRS item at
  "Often" cannot establish impulsivity, since the ASRS scores Part A as 4-of-6. That is an
  argument about the derivation, not the mapping, and `adhd_adult.yaml` carries it as an
  `open_question` while `b2ai:adhd_adult.interrupt_others -> HP:0100710` stands untouched.
- Output changes: 112 fewer assertions, all of them `excluded`. Present-pole behaviour is
  unchanged. Present poles are deliberately *not* gated on scoping — presence is existential
  over the window ("had this on several days in a fortnight" is a defensible positive claim),
  absence is universal over a life.
- Two files to keep in sync instead of one. Mitigated by the anchoring check, which makes
  drift a CI failure rather than a silent inconsistency.
- The `unverified` window on the Dyspnea Index is now explicit data rather than a footnote. It
  means *unknown*, never *unbounded*; its absent poles stay unemittable for the same reason
  the bounded instruments' do.

## Alternatives considered

- **Just delete the 26 absent rows** (the literal ask). Rejected: it discards real curation,
  leaves `when_value` fused to the mapping — so the reviewer's actual point goes unaddressed —
  and leaves the recall window with nowhere to live, which is what makes absence permanently
  unrepresentable rather than merely blocked on data.
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
