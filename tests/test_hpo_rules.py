"""Deriving PhenotypicFeatures from answers — including the absent-pole scoping gate."""

from b2ai_dataset_ingest.mapping.conditions import parse_condition
from b2ai_dataset_ingest.mapping.derivations import DerivationRule, RecallWindow
from b2ai_dataset_ingest.mapping.hpo_rules import (
    SELF_REPORT_EVIDENCE,
    derive_features,
    scoped_onset,
)
from b2ai_dataset_ingest.model import TimePoint
from b2ai_dataset_ingest.reporting import IngestReport

TWO_WEEKS = RecallWindow(iso8601="P2W", text="over the last 2 weeks", source="data_dict")
NO_WINDOW = RecallWindow(iso8601=None, text=None, source="unverified")

_SCALE = {"Not at all": 0, "Several days": 1, "Nearly every day": 3}


def _RESOLVE(column: str, raw: str) -> int | None:
    """Test stand-in for the engine's ordinal resolution: (column, raw) -> score."""
    return _SCALE.get(raw)


def _rule(**kw) -> DerivationRule:
    defaults = dict(
        subject_id="b2ai:phq9.feeling_depressed",
        table="phq9",
        column="feeling_depressed",
        object_id="HP:5200273",
        object_label="Pathological sadness",
        pole="present",
        condition=parse_condition(">=1"),
        when_value=">=1",
        window=TWO_WEEKS,
        instrument_label="PHQ-9",
        confidence="0.8",
    )
    defaults.update(kw)
    return DerivationRule(**defaults)


def _absent(**kw) -> DerivationRule:
    return _rule(pole="absent", condition=parse_condition("==0"), when_value="==0", **kw)


# -------------------------------------------------------------------- absence scoping


def test_scoped_onset_needs_both_a_timestamp_and_a_window():
    """Either half missing means the absence cannot be bounded, so it must not be asserted."""
    dated = TimePoint(session_id="s", timestamp="2026-03-01T00:00:00Z")
    assert scoped_onset(dated, NO_WINDOW) is None  # window unknown
    assert scoped_onset(TimePoint(session_id="s"), TWO_WEEKS) is None  # no observation time
    assert scoped_onset(None, TWO_WEEKS) is None


def test_scoped_onset_builds_the_interval_the_answer_actually_covers():
    dated = TimePoint(session_id="s", timestamp="2026-03-01T00:00:00Z")
    onset = scoped_onset(dated, TWO_WEEKS)
    assert onset.interval_start == "2026-02-15T00:00:00Z"
    assert onset.interval_end == "2026-03-01T00:00:00Z"
    assert onset.session_id == "s"  # the rest of the TimePoint is preserved


def test_scoped_onset_handles_calendar_months_and_short_months():
    dated = TimePoint(session_id="s", timestamp="2026-03-31T00:00:00Z")
    six = scoped_onset(dated, RecallWindow(iso8601="P6M", text=None, source="published_instrument"))
    assert six.interval_start == "2025-09-30T00:00:00Z"
    one = scoped_onset(dated, RecallWindow(iso8601="P1M", text=None, source="published_instrument"))
    assert one.interval_start == "2026-02-28T00:00:00Z"  # clamped, not an error


def test_scoped_onset_rejects_unusable_inputs():
    dated = TimePoint(session_id="s", timestamp="2026-03-01T00:00:00Z")
    prose = RecallWindow(iso8601="2 weeks", text=None, source="data_dict")
    assert scoped_onset(dated, prose) is None
    undated = TimePoint(session_id="s", timestamp="last tuesday")
    assert scoped_onset(undated, TWO_WEEKS) is None


# ------------------------------------------------------------------------ derivation


def test_present_pole_derives_feature_with_provenance():
    rules = {"feeling_depressed": [_rule()]}
    time = TimePoint(session_id="ses-baseline")
    report = IngestReport()
    [feature] = derive_features(
        {"feeling_depressed": "Several days"}, rules, _RESOLVE, time, report
    )
    assert feature.type.id == "HP:5200273"
    assert feature.excluded is False
    assert feature.onset is time
    assert report.features_derived == 1
    # Provenance: a human-readable description + an ECO self-report Evidence to the source item.
    assert "feeling_depressed" in feature.description
    assert ">=1" in feature.description
    assert "over the last 2 weeks" in feature.description  # the window is stated, not implied
    [evidence] = feature.evidence
    assert evidence.evidence_code == SELF_REPORT_EVIDENCE
    assert evidence.reference.id == "b2ai:phq9.feeling_depressed"
    assert evidence.reference.reference.endswith("#phq9.feeling_depressed")


def test_absent_pole_is_skipped_and_counted_when_it_cannot_be_scoped():
    """ADR-0003: an `excluded` with no bounded period reads as lifetime absence, so it is
    withheld rather than published unqualified. This is the case for every real session
    today — Bridge2AI-Voice session ids are opaque hashes with no timestamp."""
    rules = {"feeling_depressed": [_absent()]}
    report = IngestReport()
    features = derive_features(
        {"feeling_depressed": "Not at all"}, rules, _RESOLVE, TimePoint(session_id="ses-x"), report
    )
    assert features == []
    assert report.absent_features_unscoped == 1
    assert report.features_derived == 0


def test_absent_pole_is_emitted_once_the_window_can_be_scoped():
    """The path forward: give the session a timestamp and the same rule derives a *bounded*
    exclusion, with no change to the curation."""
    rules = {"feeling_depressed": [_absent()]}
    time = TimePoint(session_id="ses-baseline", timestamp="2026-03-01T00:00:00Z")
    report = IngestReport()
    [feature] = derive_features(
        {"feeling_depressed": "Not at all"}, rules, _RESOLVE, time, report
    )
    assert feature.excluded is True
    assert feature.onset.interval_start == "2026-02-15T00:00:00Z"
    assert feature.onset.interval_end == "2026-03-01T00:00:00Z"
    assert report.absent_features_unscoped == 0
    assert report.features_derived == 1


def test_blank_and_unmatched_cells_assert_nothing():
    rules = {"feeling_depressed": [_rule()]}  # gate is >=1
    assert derive_features({"feeling_depressed": ""}, rules, _RESOLVE) == []
    assert derive_features({}, rules, _RESOLVE) == []
    assert derive_features({"feeling_depressed": "Not at all"}, rules, _RESOLVE) == []


def test_present_and_absent_rules_are_mutually_exclusive_by_answer():
    rules = {"feeling_depressed": [_rule(), _absent()]}
    dated = TimePoint(session_id="s", timestamp="2026-03-01T00:00:00Z")
    [present] = derive_features({"feeling_depressed": "Several days"}, rules, _RESOLVE, dated)
    assert present.excluded is False
    [absent] = derive_features({"feeling_depressed": "Not at all"}, rules, _RESOLVE, dated)
    assert absent.excluded is True
