"""Apply path for the derivation rules: answers -> HPO ``PhenotypicFeature``\\s.

:mod:`~b2ai_dataset_ingest.mapping.derivations` loads the rules; this module evaluates them
against one answered row. Each derived feature carries provenance — a human-readable
description and a GA4GH ``Evidence`` with an ECO self-report code and an ``ExternalReference``
to the source item — so a questionnaire-derived phenotype is never mistaken for a
clinician-observed finding.

**The absent pole is gated on being scopable** (ADR-0003). ``PhenotypicFeature.excluded =
true`` carries no time scope of its own, so an absent pole derived from "not at all *in the
past two weeks*" would publish as unqualified lifetime absence — the reason a clinical review
asked for the absent poles to be removed. Rather than delete the curation,
:func:`scoped_onset` converts the instrument's recall window into a concrete
``TimeInterval`` against the session's observation time, and :func:`derive_features` emits an
absent feature **only** when that succeeds. Bridge2AI-Voice 3.1.0 session ids are opaque
hashes with no timestamp, so today it succeeds for no session and no absent feature is
emitted; the moment session timestamps exist, absence becomes representable — correctly
scoped — with no re-curation. Skips are counted in the report, never silently dropped.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta

from b2ai_dataset_ingest.mapping.conditions import Answer
from b2ai_dataset_ingest.mapping.derivations import DerivationRule, RecallWindow
from b2ai_dataset_ingest.model import (
    Evidence,
    ExternalReference,
    OntologyTerm,
    PhenotypicFeatureObservation,
    TimePoint,
)
from b2ai_dataset_ingest.ontology.curie_map import expand
from b2ai_dataset_ingest.reporting import IngestReport

logger = logging.getLogger(__name__)

#: ECO term for "self-reported patient statement evidence used in automatic assertion". Stamped
#: on every derived feature so self-report-derived phenotypes stay distinguishable from observed
#: findings (verified real + non-obsolete via OLS4/oaklib; ADR-0002 decision 4).
SELF_REPORT_EVIDENCE = OntologyTerm(
    id="ECO:0006160",
    label="self-reported patient statement evidence used in automatic assertion",
)

#: Date-only ISO-8601 durations — the only shape a recall window takes (``P2W``, ``P1M``,
#: ``P6M``). Time components are rejected rather than silently ignored.
_ISO_DURATION = re.compile(
    r"^P(?!$)(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?$"
)


# ------------------------------------------------------------------------ absence scoping


def scoped_onset(time: TimePoint | None, window: RecallWindow) -> TimePoint | None:
    """The interval an absent assertion is scoped to, or ``None`` when it cannot be scoped.

    An absent pole is only publishable as "absent *over this period*", which needs both a
    known recall window and an observation time to anchor it to. Returns a copy of ``time``
    carrying ``[observation - window, observation]``; ``None`` when either is missing, which
    is the signal to skip the assertion entirely.
    """
    if time is None or not time.timestamp or not window.is_known:
        return None
    start = _shift_back(time.timestamp, window.iso8601 or "")
    if start is None:
        return None
    return time.model_copy(update={"interval_start": start, "interval_end": time.timestamp})


def _shift_back(timestamp: str, duration: str) -> str | None:
    """``("2026-03-01T00:00:00Z", "P2W")`` -> ``"2026-02-15T00:00:00Z"``; None if unparseable."""
    match = _ISO_DURATION.match(duration.strip())
    if match is None:
        logger.warning("unsupported recall window %r; absence cannot be scoped", duration)
        return None
    try:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("unparseable observation timestamp; absence cannot be scoped")
        return None
    parts = {k: int(v) for k, v in match.groupdict(default="0").items()}
    months = parts["years"] * 12 + parts["months"]
    if months:
        total = (moment.year * 12 + moment.month - 1) - months
        year, month = divmod(total, 12)
        # clamp the day so e.g. 31 March minus one month is 28/29 February, not an error
        day = min(moment.day, _days_in_month(year, month + 1))
        moment = moment.replace(year=year, month=month + 1, day=day)
    moment -= timedelta(weeks=parts["weeks"], days=parts["days"])
    return moment.isoformat().replace("+00:00", "Z")


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (datetime(year, month + 1, 1) - datetime(year, month, 1)).days


# ------------------------------------------------------------------------ derivation


def derive_features(
    row: dict[str, str],
    table_rules: dict[str, list[DerivationRule]],
    resolve_ordinal: Callable[[str, str], int | None],
    time: TimePoint | None = None,
    report: IngestReport | None = None,
) -> list[PhenotypicFeatureObservation]:
    """Emit HPO ``PhenotypicFeature``s for the rules that match this row's answered cells.

    ``table_rules`` is the ``column -> [rules]`` map for this table (from
    :func:`~b2ai_dataset_ingest.mapping.derivations.load_derivation_rules`).
    ``resolve_ordinal(column, raw)`` returns the ordinal score the reader resolved for a cell
    (``None`` if unresolved), used for numeric conditions; string conditions read the raw
    cell. A blank cell asserts nothing. Absent-pole rules whose recall window cannot be
    resolved against ``time`` are skipped and counted (see :func:`scoped_onset`).
    """
    out: list[PhenotypicFeatureObservation] = []
    unscoped = 0
    for column, rules in table_rules.items():
        raw = (row.get(column) or "").strip()
        if not raw:
            continue
        answer = Answer(raw=raw, ordinal=resolve_ordinal(column, raw))
        for rule in rules:
            if not rule.condition.matches(answer):
                continue
            if rule.excluded:
                onset = scoped_onset(time, rule.window)
                if onset is None:
                    unscoped += 1
                    continue
            else:
                onset = time
            out.append(_feature_from_rule(rule, onset))
    if report is not None:
        report.features_derived += len(out)
        report.absent_features_unscoped += unscoped
    return out


def _feature_from_rule(
    rule: DerivationRule, onset: TimePoint | None
) -> PhenotypicFeatureObservation:
    return PhenotypicFeatureObservation(
        type=OntologyTerm(id=rule.object_id, label=rule.object_label or None),
        excluded=rule.excluded,
        onset=onset,
        description=_describe(rule),
        evidence=[
            Evidence(
                evidence_code=SELF_REPORT_EVIDENCE,
                reference=ExternalReference(
                    id=rule.subject_id,
                    reference=expand(rule.subject_id),
                    description=rule.subject_label or None,
                ),
            )
        ],
    )


def _describe(rule: DerivationRule) -> str:
    """Human-readable provenance: source item, pole, mapping predicate, cut-point, window."""
    target = f"{rule.object_id}" + (f" {rule.object_label}" if rule.object_label else "")
    mapping = f"[{rule.predicate_id} {target}]" if rule.predicate_id else f"[{target}]"
    item = rule.subject_id + (f" ({rule.subject_label})" if rule.subject_label else "")
    instrument = f", {rule.instrument_label}" if rule.instrument_label else ""
    scope = f" scoped to {rule.window.text}" if rule.window.text else ""
    confidence = f", confidence {rule.confidence}" if rule.confidence else ""
    return (
        f"Derived {rule.pole} {mapping} from self-reported item {item}{instrument} "
        f"when answer {rule.when_value}{scope}{confidence}."
    )
