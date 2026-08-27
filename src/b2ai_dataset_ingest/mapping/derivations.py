"""Derivation rules: how a participant's *answer* becomes a ``PhenotypicFeature``.

Rules come from **two** places, because the two poles are not the same kind of claim.

**The present pole lives in the SSSOM row**, as its ``when_value`` extension column. That is
a qualifier on the mapping's applicability — "this item is about ``HP:0012154`` *at answers
>= 1*" — which is still a statement about the item, needs nothing the mapping set cannot
carry, and reads better sitting beside the mapping it qualifies. It is spec-compliant and
backward-compatible: an SSSOM-core consumer ignores the column and still gets the mapping.

**The absent pole lives in** ``mappings/derivations/<instrument>.yaml``, for two reasons
(ADR-0003). It has no legal SSSOM expression at all: the only slot for it,
``predicate_modifier: Not``, negates *the mapping* per the spec ("subject is **not** a
predicate match to object"), not the phenotype — so the old present/absent row pair asserted
a contradiction. And ``excluded = true`` is unqualified unless something bounds it, so an
absent pole derived from "not at all **in the past two weeks**" published as lifetime
absence. Bounding it needs the instrument's **recall window**, which is a property of the
instrument rather than of any one mapping, and which no SSSOM slot carries.

So each file holds what only it can. The instrument file also carries the ``scoring_reference``
behind both poles' cut-points and any ``open_question`` about them.
:class:`RecallWindow` makes the window machine-readable, and
:mod:`~b2ai_dataset_ingest.mapping.hpo_rules` emits an absent pole only when it resolves
against a session timestamp into a concrete interval — see
:func:`~b2ai_dataset_ingest.mapping.hpo_rules.scoped_onset`.

The loader is **tolerant**, mirroring the rest of the reader: a malformed rule is logged (by
subject — mapping metadata, never PHI) and skipped, because ``b2ai-ingest validate-mappings``
is the enforcing gate in CI.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from b2ai_dataset_ingest.mapping.conditions import (
    ConditionParseError,
    ValueCondition,
    parse_condition,
)
from b2ai_dataset_ingest.mapping.sssom_io import (
    MetadataError,
    default_mapping_files,
    parse_sssom,
)

logger = logging.getLogger(__name__)

#: Where a recall window came from. ``unverified`` means *unknown*, never *unbounded* — the
#: data dictionary's silence is a gap in the dictionary, not a property of the instrument.
WINDOW_SOURCES = frozenset({"data_dict", "published_instrument", "unverified"})

#: Reasons a curator declined to author a pole, recorded so the gap is explicit, not silent.
UNAUTHORABLE_REASONS = frozenset(
    {
        "conflated-superset",  # object subsumes more than the item asks about
        "conflated-sense",  # item conflates senses; an answer can't say which was meant
        "baseline-relative",  # "more than usual" — 0 means not worse, not absent
        "intensity-qualified",  # 0 denies an escalation, not the phenotype
    }
)

#: Both poles are still modelled, but they are *authored* in different files: ``present`` in
#: the SSSOM row's ``when_value`` column, ``absent`` in the instrument file. The validator uses
#: this to reject a ``present`` block that has strayed into a rule file.
POLES = ("present", "absent")


@dataclass(frozen=True)
class RecallWindow:
    """The period an instrument's answers are scoped to (PHQ-9: "over the last 2 weeks")."""

    iso8601: str | None  # e.g. "P2W"; None when no window is known
    text: str | None  # the instrument's own phrasing, for provenance
    source: str  # one of WINDOW_SOURCES
    note: str = ""

    @property
    def is_known(self) -> bool:
        """True when the window is a duration we can subtract from an observation time."""
        return bool(self.iso8601)


@dataclass(frozen=True)
class DerivationRule:
    """One pole of one item->term derivation: assert ``object_id`` when the answer matches."""

    subject_id: str  # b2ai:<table>.<column>
    table: str
    column: str
    object_id: str  # HP:XXXXXXX
    object_label: str
    pole: str  # "present" | "absent"
    condition: ValueCondition
    when_value: str  # raw expression, kept for provenance
    window: RecallWindow
    instrument_label: str = ""
    confidence: str = ""
    #: The source item's own question text, for the derived feature's ExternalReference.
    subject_label: str = ""
    #: The mapping's SKOS predicate. Carried into provenance because it grades the claim: a
    #: feature derived through a broadMatch is weaker than one through an exactMatch.
    predicate_id: str = ""

    @property
    def excluded(self) -> bool:
        """True when this rule asserts the *absent* pole (-> ``PhenotypicFeature.excluded``)."""
        return self.pole == "absent"


def default_derivation_files(repo_root: Path | None = None) -> list[Path]:
    """The shipped rule files under ``mappings/derivations/``."""
    root = repo_root or Path(__file__).resolve().parents[3]
    return sorted((root / "mappings" / "derivations").glob("*.yaml"))


def load_derivation_documents(
    paths: Iterable[Path] | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    """Parse each rule file into ``(path, document)``, skipping unreadable ones.

    The raw documents are what the validator checks; :func:`load_derivation_rules` turns them
    into the executable index the reader uses.
    """
    files = list(paths) if paths is not None else default_derivation_files()
    documents: list[tuple[Path, dict[str, Any]]] = []
    for path in files:
        try:
            document = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("%s: unreadable derivation file (%s); skipped", path.name, exc)
            continue
        if not isinstance(document, dict):
            logger.warning("%s: derivation file is not a YAML mapping; skipped", path.name)
            continue
        documents.append((path, document))
    return documents


def load_derivation_rules(
    paths: Iterable[Path] | None = None,
) -> dict[str, dict[str, list[DerivationRule]]]:
    """Load rules from both layers, indexed ``table -> column -> [rules]``.

    ``paths`` may mix ``*.sssom.tsv`` and instrument ``*.yaml`` files and is dispatched by
    suffix; the default is everything shipped under ``mappings/``. **Present** poles are read
    from each SSSOM row's ``when_value``; **absent** poles from the instrument files, which
    also supply the recall window both poles are stamped with. A pole declared
    ``unauthorable`` yields no rule — it is a recorded decision *not* to derive, not a gap.
    """
    if paths is None:
        files = list(default_mapping_files()) + list(default_derivation_files())
    else:
        files = list(paths)
    mapping_files = [p for p in files if p.name.endswith(".sssom.tsv")]
    rule_files = [p for p in files if p.suffix in (".yaml", ".yml")]

    index: dict[str, dict[str, list[DerivationRule]]] = {}
    facts = _mapping_facts(mapping_files)

    def add(rule: DerivationRule) -> None:
        index.setdefault(rule.table, {}).setdefault(rule.column, []).append(rule)

    # Instrument files first: they carry the window that the present poles also need.
    instruments: dict[str, tuple[RecallWindow, str]] = {}
    for path, document in load_derivation_documents(rule_files):
        window = _window_from(document.get("recall_window"), path.name)
        label = str(document.get("label") or document.get("instrument") or "")
        instruments[str(document.get("instrument") or path.stem)] = (window, label)
        for entry in document.get("rules") or []:
            for rule in _absent_rules_from_entry(entry, window, label, path.name, facts):
                add(rule)

    for path in mapping_files:
        for rule in _present_rules_from_mapping(path, instruments):
            add(rule)

    # Sort so emitted feature order is a property of the rules, not of which file happened to
    # contribute them or in what order rows sit in it. Without this, moving a row between files
    # silently reshuffles every phenopacket.
    return {
        table: {
            column: sorted(rules, key=lambda r: (r.pole, r.object_id))
            for column, rules in sorted(columns.items())
        }
        for table, columns in sorted(index.items())
    }


#: A table with no instrument file has no known window; absence could never be scoped for it
#: anyway, and a present pole only uses the window for provenance text.
_UNKNOWN_WINDOW = RecallWindow(iso8601=None, text=None, source="unverified")


def _mapping_facts(mapping_files: Iterable[Path]) -> dict[tuple[str, str], tuple[str, str]]:
    """``(subject_id, object_id) -> (subject_label, predicate_id)`` from the mapping sets.

    The mapping row is the authority for both, so an absent rule — whose instrument file
    records neither — reads them off the row it is anchored to rather than restating them.
    """
    facts: dict[tuple[str, str], tuple[str, str]] = {}
    for path in mapping_files:
        try:
            _, rows = parse_sssom(path)
        except (OSError, MetadataError):
            continue
        for row in rows:
            key = ((row.get("subject_id") or "").strip(), (row.get("object_id") or "").strip())
            if all(key):
                facts.setdefault(
                    key,
                    (
                        (row.get("subject_label") or "").strip(),
                        (row.get("predicate_id") or "").strip(),
                    ),
                )
    return facts


def _present_rules_from_mapping(
    path: Path, instruments: dict[str, tuple[RecallWindow, str]]
) -> Iterable[DerivationRule]:
    """Present-pole rules from a mapping set's ``when_value`` column (empty column -> none)."""
    try:
        _, rows = parse_sssom(path)
    except (OSError, MetadataError) as exc:
        logger.warning("%s: unreadable mapping set (%s); no present poles loaded", path.name, exc)
        return
    for row in rows:
        when_value = (row.get("when_value") or "").strip()
        if not when_value:
            continue  # a pure semantic mapping — it derives nothing
        subject_id = (row.get("subject_id") or "").strip()
        object_id = (row.get("object_id") or "").strip()
        parsed = _parse_subject(subject_id, object_id, path.name)
        if parsed is None:
            continue
        table, column = parsed
        try:
            condition = parse_condition(when_value)
        except ConditionParseError as exc:
            logger.warning(
                "%s: skipping %s present pole — unparseable when_value %r (%s)",
                path.name,
                subject_id,
                when_value,
                exc,
            )
            continue
        window, instrument_label = instruments.get(table, (_UNKNOWN_WINDOW, ""))
        yield DerivationRule(
            subject_id=subject_id,
            table=table,
            column=column,
            object_id=object_id,
            object_label=(row.get("object_label") or "").strip(),
            pole="present",
            condition=condition,
            when_value=when_value,
            window=window,
            instrument_label=instrument_label,
            confidence=(row.get("confidence") or "").strip(),
            subject_label=(row.get("subject_label") or "").strip(),
            predicate_id=(row.get("predicate_id") or "").strip(),
        )


def _parse_subject(subject_id: str, object_id: str, fname: str) -> tuple[str, str] | None:
    """``(table, column)`` for a well-formed b2ai subject with an HPO object, else None."""
    if not subject_id.startswith("b2ai:") or "." not in subject_id.split(":", 1)[1]:
        logger.warning("%s: skipping rule with malformed subject %r", fname, subject_id)
        return None
    if not object_id.startswith("HP:"):
        logger.warning(
            "%s: rule %s targets non-HPO object %r; only HPO features are derived",
            fname,
            subject_id,
            object_id,
        )
        return None
    table, column = subject_id.split(":", 1)[1].split(".", 1)
    return table, column


def _window_from(raw: Any, fname: str) -> RecallWindow:
    if not isinstance(raw, dict):
        logger.warning("%s: no recall_window block; treating the window as unverified", fname)
        return RecallWindow(iso8601=None, text=None, source="unverified")
    source = str(raw.get("source") or "unverified")
    if source not in WINDOW_SOURCES:
        logger.warning("%s: unknown recall_window source %r; treating as unverified", fname, source)
        source = "unverified"
    iso = raw.get("iso8601")
    return RecallWindow(
        iso8601=str(iso) if iso else None,
        text=str(raw["text"]) if raw.get("text") else None,
        source=source,
        note=str(raw.get("note") or ""),
    )


def _absent_rules_from_entry(
    entry: Any,
    window: RecallWindow,
    instrument_label: str,
    fname: str,
    facts: dict[tuple[str, str], tuple[str, str]],
) -> Iterable[DerivationRule]:
    """The absent pole of one rule entry, if it is authored (rather than ``unauthorable``).

    A ``present`` block here is ignored, not honoured: the present pole belongs in the SSSOM
    row's ``when_value``, and the validator errors on one that has strayed into a rule file.
    """
    if not isinstance(entry, dict):
        logger.warning("%s: skipping non-mapping rule entry", fname)
        return
    subject_id = str(entry.get("subject_id") or "").strip()
    object_id = str(entry.get("object_id") or "").strip()
    parsed = _parse_subject(subject_id, object_id, fname)
    if parsed is None:
        return
    table, column = parsed
    block = entry.get("absent")
    if not isinstance(block, dict):
        return
    when_value = str(block.get("when_value") or "").strip()
    if not when_value:
        return  # `unauthorable` (or empty): a recorded decision not to derive
    try:
        condition = parse_condition(when_value)
    except ConditionParseError as exc:
        logger.warning(
            "%s: skipping %s absent pole — unparseable when_value %r (%s)",
            fname,
            subject_id,
            when_value,
            exc,
        )
        return
    confidence = entry.get("confidence")
    subject_label, predicate_id = facts.get((subject_id, object_id), ("", ""))
    yield DerivationRule(
        subject_id=subject_id,
        table=table,
        column=column,
        object_id=object_id,
        object_label=str(entry.get("object_label") or "").strip(),
        pole="absent",
        condition=condition,
        when_value=when_value,
        window=window,
        instrument_label=instrument_label,
        confidence="" if confidence is None else str(confidence),
        subject_label=subject_label,
        predicate_id=predicate_id,
    )
