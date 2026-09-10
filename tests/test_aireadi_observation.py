"""observation.csv ingest: instrument items, and the scope policy around them.

observation.csv is the widest table in an AI-READI release — hundreds of item keys, of which
this pipeline ingests a handful on purpose. Two properties matter more than the item list
itself, and both are tested here:

- **"dropped by policy" and "nobody looked" stay distinguishable.** Without that, the
  unmapped count sits in the hundreds and stops meaning anything, and a genuine oversight
  hides among deliberate exclusions.
- **Every published item is accounted for.** A family with no rule and no mapping is a gap in
  the policy, not a silent no-op.
"""

from pathlib import Path

import pytest

from b2ai_dataset_ingest.mapping.loaders import load_mapping
from b2ai_dataset_ingest.sources.aireadi import AireadiSource
from b2ai_dataset_ingest.sources.aireadi.reader import _drop_prefixes, _drop_reason

CONFIG_DIR = Path(__file__).parents[1] / "config" / "aireadi"
FIXTURE = Path(__file__).parent / "data" / "aireadi"
SCOPE = CONFIG_DIR / "observation" / "scope.yaml"


@pytest.fixture
def participants():
    return {p.individual.id: p for p in AireadiSource(FIXTURE, CONFIG_DIR).read()}


@pytest.fixture
def source_report():
    source = AireadiSource(FIXTURE, CONFIG_DIR)
    list(source.read())
    return source.report


def _by_assay(packet, assay_id):
    return [m for m in packet.measurements if m.assay.id == assay_id]


# ---------- instrument items
def test_cesd_items_carry_verified_loinc_assays(participants):
    """CES-D-10 items ship LOINC, unlike PAID-5, which the source gives no public code."""
    assert _by_assay(participants["900001"], "LOINC:100772-3")  # ces3 Feeling depressed


def test_the_cesd_total_does_not_claim_an_unscoped_loinc_code(participants):
    """LOINC:100787-1 exists, but its name does not say 10-item or 20-item.

    Those totals range 0-30 and 0-60. Attaching an unscoped code to a 0-30 value would
    mislabel it in a way no consumer could detect, so the total ships a project-local id
    until the instrument scope is confirmed. Item-level codes are unambiguous and are used.
    """
    totals = _by_assay(participants["900001"], "b2ai:observation.cestl")
    assert len(totals) == 1 and totals[0].value_quantity.value == 14.0
    assert not _by_assay(participants["900001"], "LOINC:100787-1")


def test_paid_items_ship_project_local_ids(participants):
    """The documented VHI-10 stopgap: a curated label under b2ai:, upgradeable in place."""
    assert _by_assay(participants["900002"], "b2ai:observation.paid_dpr")
    assert _by_assay(participants["900002"], "b2ai:observation.paidscore")


def test_reverse_scored_items_are_emitted_as_stored(participants):
    """ces5/ces8 are positively worded and the SOURCE stores them already reversed.

    A stored 3 on ces5 means "rarely felt hopeful". Re-reversing here would double-apply the
    transform and invert the item, so the pipeline must pass the stored value straight
    through — which is exactly what this asserts.
    """
    hopeful = _by_assay(participants["900001"], "LOINC:100774-9")[0]
    happy = _by_assay(participants["900001"], "LOINC:100778-0")[0]
    assert hopeful.value_quantity.value == 3.0
    assert happy.value_quantity.value == 0.0


def test_instrument_scores_carry_the_score_unit(participants):
    """Quantity.unit is required by the schema; an ordinal is UCUM:{score} by convention."""
    for m in _by_assay(participants["900001"], "LOINC:100772-3"):
        assert m.value_quantity.unit.id == "UCUM:{score}"


def test_zero_survives_as_an_answer(participants):
    """0 is the modal answer on a screening item, not a null. Dropping it guts the instrument."""
    assert _by_assay(participants["900003"], "LOINC:100772-3")[0].value_quantity.value == 0.0


def test_refusal_sentinels_are_dropped(participants, source_report):
    """999 is "don't know", not a score of 999."""
    assert _by_assay(participants["900002"], "LOINC:100767-3") == []
    assert source_report.sentinel_answers["observation.ces1"] == 1


# ---------- the scope policy
def test_dropped_by_policy_is_distinct_from_unmapped(source_report):
    """The distinction the whole drop list exists to preserve."""
    assert source_report.items_dropped["observation.cesmpdat"] == 1  # administrative date
    assert source_report.items_dropped["observation.rtop_odd"] == 1  # imaging acquisition flag
    assert source_report.items_unmapped["observation.zzz_nonesuch"] == 1  # genuinely unknown
    assert "observation.zzz_nonesuch" not in source_report.items_dropped
    assert "observation.cesmpdat" not in source_report.items_unmapped


def test_drop_patterns_are_globs_matching_both_ends_of_a_name():
    """REDCap names families at both ends: `rtsm_*` is a prefix, `*mpdat` a suffix."""
    rules = _drop_prefixes(load_mapping(SCOPE))
    assert _drop_reason("rtop_odd", rules)  # prefix
    assert _drop_reason("paidcmpdat", rules)  # suffix
    # ...and the source's own naming is inconsistent, which the pattern must absorb:
    assert _drop_reason("cesmpdat", rules), "CES-D uses a single m; `*cmpdat` would miss it"


def test_ingested_items_are_never_also_dropped():
    """A rule that swallowed an ingested item would silently empty an instrument."""
    rules = _drop_prefixes(load_mapping(SCOPE))
    for name in ("cesd10", "paid5"):
        for item in load_mapping(CONFIG_DIR / "observation" / f"{name}.yaml").get("measures") or {}:
            assert _drop_reason(item, rules) is None, f"{item} is both ingested and dropped"


def test_every_drop_rule_states_a_reason():
    """A bare pattern with no rationale is indistinguishable from an oversight."""
    for pattern, reason in _drop_prefixes(load_mapping(SCOPE)).items():
        assert len(reason.split()) >= 5, f"{pattern} has no usable reason"


# ---------- completeness against the published item list (local only)
CROSSWALK = (
    Path(__file__).parents[1] / "data_synth" / "aireadi-docs" / "mappings.json"
)


@pytest.mark.skipif(
    not CROSSWALK.is_file(),
    reason="AI-READI published crosswalk not fetched (scripts/fetch_aireadi_crosswalk.sh)",
)
def test_no_published_observation_item_is_unaccounted_for():
    """Every item AI-READI publishes is either ingested or has a stated reason.

    This is the test that keeps the drop list honest: it fails when the source adds a family
    nobody has ruled on, rather than letting it appear as one more anonymous unmapped count.
    """
    import fnmatch
    import json
    import re

    rows = [
        r for r in json.loads(CROSSWALK.read_text())
        if r.get("temp_Question_or_Answer") == "Question" and r["SRC_CODE"].strip()
    ]
    rules = _drop_prefixes(load_mapping(SCOPE))
    ingested = set()
    for name in ("cesd10", "paid5"):
        ingested |= set(
            load_mapping(CONFIG_DIR / "observation" / f"{name}.yaml").get("measures") or {}
        )
    # Items belonging to measurement.csv, and lab rows whose SRC_CODE *is* a LOINC code.
    measurement_families = (
        "import_", "lbscat_", "bmi_", "bp1_", "bp2_", "height_", "weight_", "waist_", "hip_",
        "whr_", "pulse_", "viaod", "viaos", "plcs", "mlcs", "mss", "msl", "moca", "naming",
        "digitspan", "lettera", "subtraction", "repetition", "fluency", "delayed", "memory_",
        "trails", "cube", "clock",
    )
    loinc_code = re.compile(r"^\d+-\d$")

    unaccounted = sorted(
        item
        for item in {r["SRC_CODE"].strip() for r in rows}
        if not item.startswith(measurement_families)
        and not loinc_code.match(item)
        and item not in ingested
        and not any(fnmatch.fnmatch(item, p) or item == p for p in rules)
    )
    assert not unaccounted, (
        f"{len(unaccounted)} published observation item(s) have neither a mapping nor a drop "
        f"rule: {unaccounted[:20]}"
    )


# ---------- refusal codes must never assert a phenotype
def test_a_refusal_code_cannot_fire_an_open_ended_gate():
    """The trap this pipeline defends against twice over.

    `conditions._match_scalar` falls back to the RAW cell when the ordinal is None, so a
    refusal code reaches an open-ended comparison as an ordinary number: `>=1` matches an
    answer of 777, and so does `>=2`. Returning None for the ordinal does not save you.
    "Declined to answer" would silently assert the phenotype.
    """
    from b2ai_dataset_ingest.mapping.conditions import Answer, parse_condition

    for ordinal in (777, None):
        answer = Answer(raw="777", ordinal=ordinal)
        assert parse_condition(">=1").matches(answer) is True, "the hazard is real"
        # ...and the two defences that make it unreachable:
        assert parse_condition("in {1,2,3}").matches(answer) is False
        assert parse_condition(">=1 & <=3").matches(answer) is False


def test_a_gated_item_answered_with_a_refusal_code_is_not_buffered(source_report):
    """Defence one: the sentinel is screened before the derivation ever sees it.

    900001 answers ces7 with 777. It must be counted as a refusal, not carried into the
    gated-answer buffer where an open-ended rule could match it.
    """
    assert source_report.sentinel_answers["observation.ces7"] == 1


def test_shipped_gates_are_bounded_not_open_ended():
    """Defence two: no shipped `when_value` is an open-ended comparison.

    Belt and braces with the sentinel screen above — a bounded gate cannot fire on 555/777/
    888/999 even if a sentinel somehow reached it.
    """
    from b2ai_dataset_ingest.mapping.omop import SENTINEL_ANSWERS
    from b2ai_dataset_ingest.mapping.sssom_io import default_mapping_files, parse_sssom

    checked = 0
    for path in default_mapping_files(Path(__file__).parents[1], dataset="aireadi"):
        _, rows = parse_sssom(path)
        for row in rows:
            expression = (row.get("when_value") or "").strip()
            if not expression:
                continue
            checked += 1
            from b2ai_dataset_ingest.mapping.conditions import Answer, parse_condition

            condition = parse_condition(expression)
            for sentinel in sorted(SENTINEL_ANSWERS):
                assert not condition.matches(Answer(raw=sentinel, ordinal=int(float(sentinel)))), (
                    f"{row['subject_id']}: gate {expression!r} fires on refusal code {sentinel}"
                )
    # No gated AI-READI rows ship yet; this guards the ones that will.
    assert checked >= 0


# ---------- monofilament: the procedure_occurrence decision, in practice
def test_monofilament_results_come_from_measurement_not_procedure(participants):
    """procedure_occurrence records only that a site was TESTED; the finding is here.

    Ingesting the 22 procedure rows would emit twenty "a test happened" actions per
    participant with the result stored elsewhere, so they are deliberately not ingested.
    """
    right = _by_assay(participants["900003"], "b2ai:measurement.mssrffl")
    left = _by_assay(participants["900003"], "b2ai:measurement.msslffl")
    assert right and left
    assert right[0].value_quantity.value == 10.0
    assert left[0].value_quantity.value == 7.0


def test_monofilament_carries_the_examination_but_an_unlateralized_site(participants):
    """UBERON has `pes` and no lateralized foot, so the side is in the assay label.

    The per-eye items do encode their side structurally because UBERON *does* carry right
    and left eye. Asserting a lateralized foot would mean using `UBERON:8300003`, which is
    "right hindlimb" -- the whole limb, not the foot, and simply the wrong site.
    """
    right = _by_assay(participants["900003"], "b2ai:measurement.mssrffl")[0]
    assert right.procedure.code.id == "NCIT:C129294"
    assert right.procedure.body_site.id == "UBERON:0002387"  # pes, unlateralized
    assert "Right foot" in right.assay.label
