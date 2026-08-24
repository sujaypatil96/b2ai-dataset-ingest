"""Derivation rules: how a participant's *answer* becomes a ``PhenotypicFeature``.

This is the interpretation layer, deliberately kept **out** of the SSSOM mapping files
(ADR-0003). ``mappings/*.sssom.tsv`` records that an item is *about* an HPO concept — a
term-to-term claim that holds regardless of who answered. ``mappings/derivations/*.yaml``
records the separate, weaker, instrument-specific claim that a particular *answer* warrants
asserting that concept for a participant: the cut-point, the recall window it is scoped to,
and which of the present/absent poles a curator was willing to author.

Fusing the two (the ``when_value`` + ``predicate_modifier`` columns this module replaces)
had two defects. Semantically, SSSOM's ``predicate_modifier: Not`` negates *the mapping*
("subject is **not** a predicate match to object"), not the phenotype, so the present/absent
pair asserted a contradiction. Clinically, an ``excluded = true`` derived from "not at all
**in the past two weeks**" published as unqualified lifetime absence, because the window did
not survive into the output.

Both are fixed here. :class:`RecallWindow` carries the window as machine-readable data, and
:mod:`~b2ai_dataset_ingest.mapping.hpo_rules` emits an absent pole only when that window can
be resolved against a session timestamp into a concrete interval — see
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
    note: str = ""

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
    """Load derivation rules indexed ``table -> column -> [rules]``.

    Both poles of a rule become separate :class:`DerivationRule`\\s; a pole declared
    ``unauthorable`` yields none (it is a recorded decision *not* to derive, not a gap).
    """
    index: dict[str, dict[str, list[DerivationRule]]] = {}
    for path, document in load_derivation_documents(paths):
        window = _window_from(document.get("recall_window"), path.name)
        instrument_label = str(document.get("label") or document.get("instrument") or "")
        for entry in document.get("rules") or []:
            for rule in _rules_from_entry(entry, window, instrument_label, path.name):
                index.setdefault(rule.table, {}).setdefault(rule.column, []).append(rule)
    return index


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


def _rules_from_entry(
    entry: Any, window: RecallWindow, instrument_label: str, fname: str
) -> Iterable[DerivationRule]:
    if not isinstance(entry, dict):
        logger.warning("%s: skipping non-mapping rule entry", fname)
        return
    subject_id = str(entry.get("subject_id") or "").strip()
    object_id = str(entry.get("object_id") or "").strip()
    if not subject_id.startswith("b2ai:") or "." not in subject_id.split(":", 1)[1]:
        logger.warning("%s: skipping rule with malformed subject %r", fname, subject_id)
        return
    if not object_id.startswith("HP:"):
        logger.warning(
            "%s: rule %s targets non-HPO object %r; only HPO features are derived",
            fname,
            subject_id,
            object_id,
        )
        return
    table, column = subject_id.split(":", 1)[1].split(".", 1)
    confidence = entry.get("confidence")
    for pole in POLES:
        block = entry.get(pole)
        if not isinstance(block, dict):
            continue
        when_value = str(block.get("when_value") or "").strip()
        if not when_value:
            continue  # `unauthorable` (or empty): a recorded decision not to derive
        try:
            condition = parse_condition(when_value)
        except ConditionParseError as exc:
            logger.warning(
                "%s: skipping %s %s pole — unparseable when_value %r (%s)",
                fname,
                subject_id,
                pole,
                when_value,
                exc,
            )
            continue
        yield DerivationRule(
            subject_id=subject_id,
            table=table,
            column=column,
            object_id=object_id,
            object_label=str(entry.get("object_label") or "").strip(),
            pole=pole,
            condition=condition,
            when_value=when_value,
            window=window,
            instrument_label=instrument_label,
            confidence="" if confidence is None else str(confidence),
            note=str(block.get("note") or ""),
        )
