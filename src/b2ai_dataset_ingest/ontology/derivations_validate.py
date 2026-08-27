"""Validate the instrument rule files in ``mappings/derivations/*.yaml``.

The companion to :mod:`~b2ai_dataset_ingest.ontology.sssom_validate`. That module guards the
*mapping* layer (no hallucinated or drifted HPO terms, no ``predicate_modifier``); this one
guards the layer holding what a mapping set cannot express — the **absent** pole and the
instrument's recall window (ADR-0003). The *present* pole is not here: it is the SSSOM row's
own ``when_value``, and a ``present`` block that has strayed into a rule file is an error.

The load-bearing check is **anchoring**: every rule's ``(subject_id, object_id)`` pair must
already exist as a row in the SSSOM set. A rule says "this answer warrants asserting that
term"; it may not invent the underlying claim that the item is about the term. Without this,
the two layers could drift apart silently and a derived ``PhenotypicFeature`` would have no
mapping to justify it.

Everything else is structural: a file's ``instrument`` must match its filename (that stem is
what joins a rule to a data table, and to the present poles that borrow its window), the
``absent`` pole must declare exactly one of ``when_value`` or ``unauthorable``, conditions must
parse, ``unauthorable`` reasons must come from the closed set in
:mod:`~b2ai_dataset_ingest.mapping.derivations`, and recall windows must be durations the apply
path can actually subtract. As with cut-points, whether a threshold is *clinically* right is a
curator judgment this cannot check.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from b2ai_dataset_ingest.mapping.conditions import ConditionParseError, parse_condition
from b2ai_dataset_ingest.mapping.derivations import (
    UNAUTHORABLE_REASONS,
    WINDOW_SOURCES,
    default_derivation_files,
    load_derivation_documents,
)
from b2ai_dataset_ingest.mapping.sssom_io import default_mapping_files, parse_sssom
from b2ai_dataset_ingest.ontology.sssom_validate import Finding

REQUIRED_KEYS = ("instrument", "label", "recall_window", "scoring_reference", "rules")


def sssom_pairs(paths: Iterable[Path] | None = None) -> set[tuple[str, str]]:
    """Every ``(subject_id, object_id)`` pair the mapping set asserts."""
    pairs: set[tuple[str, str]] = set()
    for path in list(paths) if paths is not None else default_mapping_files():
        try:
            _, rows = parse_sssom(path)
        except Exception:  # noqa: BLE001 - sssom_validate reports the parse failure itself
            continue
        for row in rows:
            subject = (row.get("subject_id") or "").strip()
            obj = (row.get("object_id") or "").strip()
            if subject and obj:
                pairs.add((subject, obj))
    return pairs


def validate_derivations(
    paths: Iterable[Path] | None = None,
    mapping_paths: Iterable[Path] | None = None,
) -> tuple[list[Finding], int]:
    """Validate rule files; returns ``(findings, n_rules)``."""
    files = list(paths) if paths is not None else default_derivation_files()
    anchors = sssom_pairs(mapping_paths)
    findings: list[Finding] = []
    n_rules = 0
    seen: set[tuple[str, str]] = set()
    for path, document in load_derivation_documents(files):
        findings.extend(_check_document(document, path, anchors, seen))
        n_rules += len(document.get("rules") or [])
    findings.extend(check_present_poles_have_an_instrument(mapping_paths, files))
    return findings, n_rules


def _check_document(
    document: dict[str, Any],
    path: Path,
    anchors: set[tuple[str, str]],
    seen: set[tuple[str, str]],
) -> Iterable[Finding]:
    fname = path.name

    def err(subject: str, code: str, message: str) -> Finding:
        return Finding(fname, subject, "error", code, message)

    for key in REQUIRED_KEYS:
        if not document.get(key):
            yield err("-", "missing-field", f"missing required key {key!r}")

    instrument = str(document.get("instrument") or "").strip()
    if instrument and instrument != path.stem:
        yield err(
            "-",
            "instrument-mismatch",
            f"instrument {instrument!r} must match the filename stem {path.stem!r} — that "
            f"stem is what joins a rule to its data table",
        )

    yield from _check_window(document.get("recall_window"), fname)

    for entry in document.get("rules") or []:
        if not isinstance(entry, dict):
            yield err("-", "bad-rule", "rule entry is not a mapping")
            continue
        subject = str(entry.get("subject_id") or "").strip()
        obj = str(entry.get("object_id") or "").strip()
        ident = subject or "<no subject_id>"

        if not subject.startswith("b2ai:") or "." not in subject.split(":", 1)[1]:
            yield err(ident, "malformed-subject", "subject must be b2ai:<table>.<column>")
            continue
        table = subject.split(":", 1)[1].split(".", 1)[0]
        if instrument and table != instrument:
            yield err(
                ident,
                "wrong-instrument",
                f"subject's table {table!r} does not match this file's instrument {instrument!r}",
            )
        if not obj.startswith("HP:"):
            yield err(ident, "bad-object", f"object_id must be an HP: CURIE, got {obj!r}")
            continue

        # The load-bearing check: a derivation may not invent the mapping it derives from.
        if (subject, obj) not in anchors:
            yield err(
                ident,
                "unanchored-rule",
                f"no mappings/*.sssom.tsv row maps {subject} -> {obj}; a derivation rule "
                f"cannot invent the mapping it interprets",
            )
        if (subject, obj) in seen:
            yield err(ident, "duplicate-rule", f"duplicate rule for {subject} -> {obj}")
        seen.add((subject, obj))

        yield from _check_confidence(entry.get("confidence"), ident, fname)
        yield from _check_poles(entry, ident, fname)


def _check_window(raw: Any, fname: str) -> Iterable[Finding]:
    if not isinstance(raw, dict):
        yield Finding(fname, "-", "error", "bad-window", "recall_window must be a mapping")
        return
    source = str(raw.get("source") or "")
    if source not in WINDOW_SOURCES:
        yield Finding(
            fname, "-", "error", "bad-window-source",
            f"recall_window.source {source!r} not in {sorted(WINDOW_SOURCES)}",
        )
    iso = raw.get("iso8601")
    if iso:
        # Import here: the shift helper lives with the apply path, not the rule model.
        from b2ai_dataset_ingest.mapping.hpo_rules import _ISO_DURATION

        if not _ISO_DURATION.match(str(iso).strip()):
            yield Finding(
                fname, "-", "error", "bad-window-duration",
                f"recall_window.iso8601 {iso!r} is not a date-only ISO-8601 duration "
                f"(P[n]Y[n]M[n]W[n]D) the apply path can subtract",
            )
    elif source != "unverified":
        yield Finding(
            fname, "-", "warning", "window-source-without-duration",
            f"recall_window.source is {source!r} but no iso8601 duration is given, so absent "
            f"poles on this instrument can never be scoped",
        )


def _check_confidence(raw: Any, ident: str, fname: str) -> Iterable[Finding]:
    if raw is None:
        return
    try:
        value = float(raw)
    except (TypeError, ValueError):
        yield Finding(
            fname, ident, "error", "bad-confidence", f"confidence {raw!r} is not a number"
        )
        return
    if not 0.0 <= value <= 1.0:
        yield Finding(fname, ident, "error", "bad-confidence", f"confidence {value} out of [0,1]")


def _check_poles(entry: dict[str, Any], ident: str, fname: str) -> Iterable[Finding]:
    if "present" in entry:
        yield Finding(
            fname, ident, "error", "present-in-rule-file",
            "the present pole belongs in the SSSOM row's when_value column, not here — "
            "only the absent pole (which has no legal SSSOM expression) lives in a rule file",
        )
    block = entry.get("absent")
    if block is None:
        yield Finding(
            fname, ident, "error", "no-absent-pole",
            "rule entry declares no absent pole, so it does nothing; delete it, or record why "
            "the pole is declined with `absent: {unauthorable: ...}`",
        )
        return
    if not isinstance(block, dict):
        yield Finding(fname, ident, "error", "bad-pole", "'absent' must be a mapping")
        return

    when_value = str(block.get("when_value") or "").strip()
    unauthorable = str(block.get("unauthorable") or "").strip()
    if when_value and unauthorable:
        yield Finding(
            fname, ident, "error", "ambiguous-pole",
            "'absent' declares both when_value and unauthorable; a pole is either derived or "
            "explicitly declined, not both",
        )
    elif not when_value and not unauthorable:
        yield Finding(
            fname, ident, "error", "empty-pole",
            "'absent' declares neither when_value nor unauthorable",
        )
    if when_value:
        try:
            parse_condition(when_value)
        except ConditionParseError as exc:
            yield Finding(
                fname, ident, "error", "bad-when-value",
                f"absent when_value {when_value!r} does not parse: {exc}",
            )
    if unauthorable:
        if unauthorable not in UNAUTHORABLE_REASONS:
            yield Finding(
                fname, ident, "error", "bad-unauthorable-reason",
                f"absent unauthorable {unauthorable!r} not in {sorted(UNAUTHORABLE_REASONS)}",
            )
        if not str(block.get("note") or "").strip():
            yield Finding(
                fname, ident, "warning", "undocumented-decline",
                f"absent is declined as {unauthorable!r} with no note explaining why",
            )


def check_present_poles_have_an_instrument(
    mapping_paths: Iterable[Path] | None = None,
    rule_paths: Iterable[Path] | None = None,
) -> Iterable[Finding]:
    """Warn when a gated mapping's table has no instrument file to supply its recall window.

    A present pole still derives without one, but it is stamped with no window, and the table's
    absent poles could never be scoped — usually the sign of a missing rule file rather than a
    deliberate choice.
    """
    known = {
        str(document.get("instrument") or path.stem)
        for path, document in load_derivation_documents(
            list(rule_paths) if rule_paths is not None else None
        )
    }
    seen: set[str] = set()
    for path in list(mapping_paths) if mapping_paths is not None else default_mapping_files():
        try:
            _, rows = parse_sssom(path)
        except Exception:  # noqa: BLE001 - sssom_validate reports the parse failure itself
            continue
        for row in rows:
            subject = (row.get("subject_id") or "").strip()
            if not (row.get("when_value") or "").strip() or not subject.startswith("b2ai:"):
                continue
            table = subject.split(":", 1)[1].split(".", 1)[0]
            if table in known or table in seen:
                continue
            seen.add(table)
            yield Finding(
                path.name, subject, "warning", "no-instrument-file",
                f"table {table!r} has gated mappings but no mappings/derivations/{table}.yaml, "
                f"so its recall window is unknown and its features carry no scope",
            )
