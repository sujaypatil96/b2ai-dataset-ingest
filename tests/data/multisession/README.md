# Multi-session fixture

A hand-crafted, deliberately **multi-session** participant (`ms-0001`) used to exercise
time-course handling, which the real synthetic data cannot — it only has `ses-baseline`.

`questionnaire/phq9.tsv` has the same participant at two sessions (`ses-baseline`,
`ses-followup`) with different answers, so each maps to its own time-stamped observation
(`TimeElement`) in the output phenopacket.

These are minimal column subsets of the real tables — enough to test grouping by
`participant_id` and ordering observations by `session_id`, not full fidelity.
