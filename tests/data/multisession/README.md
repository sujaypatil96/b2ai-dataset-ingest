# Multi-session fixture

A hand-crafted, deliberately **multi-session** participant (`ms-0001`) used to exercise
time-course handling, which the real synthetic data cannot — it only has `ses-baseline`.

`questionnaire/phq9.tsv` has the same participant at two sessions (`ses-baseline`,
`ses-followup`) with different answers, so each maps to its own time-stamped observation
(`TimeElement`) in the output phenopacket.

`questionnaire/vhi10.tsv` carries a populated `vhi_10_calc_score` (which the real
synthetic data never fills), so the end-to-end test also exercises the precomputed-total
Measurement and the project-local `b2ai:` VHI-10 item codes.

None of these questionnaire fixtures ship a companion ReproSchema `.json` data dict, so
they also exercise the engine's `ordinal_scale` fallback (answer→value map from config).

These are minimal column subsets of the real tables — enough to test grouping by
`participant_id` and ordering observations by `session_id`, not full fidelity.
