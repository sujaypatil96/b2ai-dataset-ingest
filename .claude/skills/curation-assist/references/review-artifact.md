# Review artifact — what to hand a curator

The output of a proposal run is **not** a finished SSSOM file. It is a review table an expert
can skim and accept/amend, with the deterministic and judgment parts clearly separated.

## Format

One row per candidate mapping:

| subject (column) | source description | proposed object | pred | conf | rationale / alternatives | ✅ auto-verified | ⚖️ needs sign-off |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `b2ai:phq9.no_appetite` | "poor appetite or overeating" | HP:0100738 Abnormal eating behavior | broad | 0.8 | conflates two poles; alt: split Poor appetite + Polyphagia | code exists, not obsolete, label matches | concept + predicate |

Plus, for the run:
- an **out-of-scope list** — columns skipped, each with its bucket (`scope-checklist.md`), so
  coverage is explicit, not silently partial;
- a **flagged list** — lexical-vs-semantic traps and grey-area calls that specifically need a
  human (e.g. `dizziness`→Vertigo).

## The two columns that matter

- **✅ auto-verified** is filled by the deterministic gate (`b2ai-ingest validate-mappings`):
  the code is real, current, and correctly labelled. If this is not green, the row is not
  ready — fix before review.
- **⚖️ needs sign-off** is the human's job: *is this the right concept, and is the predicate
  direction/strength right?* A green auto-verified column does **not** answer this.

## Closing the loop (why this compounds)

When the expert changes a call, capture the decision so the next run is more consistent:

- a **scope** change → add/annotate a bucket or example in `scope-checklist.md`;
- a **concept/predicate** change → add a worked example (and, if general, a rule) to
  `predicate-rules.md`;
- a recurring **wrong lexical hit** → note the trap in `predicate-rules.md`.

Do this in the same PR as the mapping change, so the rulebook and the mappings evolve
together. Each cycle narrows the judgment variance — the skill gets better *because* experts
correct it, not despite them.
