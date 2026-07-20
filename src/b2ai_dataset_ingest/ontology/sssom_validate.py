"""Validate the B2AI -> HPO SSSOM mapping files.

This is the durable, in-repo guardrail against hallucinated / drifted ontology terms. It runs
three layers of checks and returns structured :class:`Finding` objects:

1. **Structural** (always, offline, no deps): required columns, a known ``skos:`` predicate,
   a ``mapping_justification``, a well-formed ``b2ai:<table>.<column>`` subject, a well-formed
   ``HP:`` object CURIE, in-range ``confidence``, no duplicate ``(subject, predicate, object)``
   triple (across the whole set), and every CURIE prefix used declared in the file's own
   ``curie_map`` (self-containment).
2. **Subject existence** (offline, when a ``data_root`` is given): each ``b2ai:<table>.<column>``
   subject must name a real column in the corresponding data dictionary
   (``<data_root>/**/<table>.json``, via :func:`mapping.loaders.load_data_dict`). Skipped (not
   failed) when no data root is available; unresolved tables are counted and surfaced.
3. **HPO anti-hallucination** (via oaklib's offline HPO SQLite, when available): every
   ``object_id`` must exist, not be deprecated (checked against ``owl:deprecated`` via
   ``adapter.obsoletes()`` -- not merely the ``"obsolete "`` label convention), and its
   ``object_label`` must equal HPO's authoritative label (an *exact* synonym only warns). The
   loaded HPO version is compared to each file's ``object_source_version`` and surfaced, so a
   green run is auditable and drift is visible. Skipped (not failed) when oaklib/the HP backend
   is unavailable, unless ``check_ontology`` forces it.

The SSSOM/TSV parser is intentionally dependency-light (stdlib + PyYAML, already a project
dep) so structural + subject checks never need the heavy ontology stack.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from b2ai_dataset_ingest.mapping.loaders import load_data_dict

logger = logging.getLogger(__name__)

# oaklib adapter selector for the offline HPO SQLite (matches ontology/terms.py).
HP_ADAPTER = "sqlite:obo:hp"

ALLOWED_PREDICATES = frozenset(
    {
        "skos:exactMatch",
        "skos:broadMatch",
        "skos:narrowMatch",
        "skos:relatedMatch",
        "skos:closeMatch",
    }
)
REQUIRED_COLUMNS = ("subject_id", "predicate_id", "object_id", "mapping_justification")
_RELEASE_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class Finding:
    """One validation problem. ``error`` findings should fail CI; ``warning`` are advisory."""

    file: str
    subject: str
    severity: str  # "error" | "warning"
    code: str
    message: str

    def render(self) -> str:
        return f"[{self.severity.upper()}] {self.file}: {self.subject}: {self.code}: {self.message}"


@dataclass
class ValidationResult:
    findings: list[Finding] = field(default_factory=list)
    n_rows: int = 0
    ontology_checked: bool = False
    subjects_checked: bool = False
    hpo_version: str | None = None
    subjects_unresolved: int = 0  # subjects whose data-dict table could not be resolved

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    def render(self) -> str:
        lines = [f.render() for f in self.findings]
        ont = (
            f"ontology=oaklib@{self.hpo_version or '?'}"
            if self.ontology_checked
            else "ontology=SKIPPED"
        )
        subj = "subjects=data-dict" if self.subjects_checked else "subjects=SKIPPED"
        if self.subjects_checked and self.subjects_unresolved:
            subj += f" ({self.subjects_unresolved} unresolved)"
        lines.append(
            f"checked {self.n_rows} mappings ({ont}, {subj}): "
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        )
        return "\n".join(lines)


# --------------------------------------------------------------------------- parsing


class MetadataError(ValueError):
    """Raised when the SSSOM metadata header is not parseable YAML."""


def parse_sssom(path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Parse a SSSOM/TSV file into ``(metadata, rows)``.

    The commented (``#``) prologue is joined and parsed as the SSSOM YAML metadata block; the
    remaining lines are a TSV whose first row is the header. Raises :class:`MetadataError` if
    the header is not valid YAML.
    """
    meta_lines: list[str] = []
    tsv_lines: list[str] = []
    for raw in path.read_text().splitlines():
        if raw.startswith("#"):
            content = raw[1:]
            meta_lines.append(content[1:] if content.startswith(" ") else content)
        elif raw.strip():
            tsv_lines.append(raw)
    try:
        metadata = yaml.safe_load("\n".join(meta_lines)) if meta_lines else {}
    except yaml.YAMLError as exc:
        raise MetadataError(str(exc)) from exc
    if not isinstance(metadata, dict):
        metadata = {}
    rows: list[dict[str, str]] = []
    if tsv_lines:
        header = tsv_lines[0].split("\t")
        for line in tsv_lines[1:]:
            cells = line.split("\t")
            # pad short rows so trailing empty cells (e.g. blank comment) don't misalign
            cells += [""] * (len(header) - len(cells))
            rows.append(dict(zip(header, cells, strict=False)))
    return metadata, rows


# ------------------------------------------------------------------- ontology backend


def _get_hp_adapter():
    """Return an oaklib HPO adapter, or None if oaklib / the HP backend is unavailable."""
    try:
        from oaklib import get_adapter
    except ImportError:
        return None
    try:
        return get_adapter(HP_ADAPTER)
    except Exception as exc:  # noqa: BLE001 - oaklib raises many backend/network errors
        logger.warning("oaklib HPO adapter unavailable (%s); ontology checks skipped", exc)
        return None


def _adapter_hpo_version(adapter) -> str | None:
    """Best-effort ``owl:versionIRI`` release date of the loaded HPO (e.g. ``2026-02-16``)."""
    try:
        from sqlalchemy import text

        with adapter.engine.connect() as conn:
            rows = conn.execute(
                text("select object from statements where predicate='owl:versionIRI' limit 1")
            ).fetchall()
        if rows:
            m = _RELEASE_DATE.search(str(rows[0][0]))
            return m.group(1) if m else str(rows[0][0])
    except Exception as exc:  # noqa: BLE001 - version is best-effort, never fatal
        logger.debug("could not read HPO versionIRI: %s", exc)
    return None


def _obsolete_ids(adapter) -> set[str]:
    """The set of deprecated HP CURIEs (``owl:deprecated``), or empty on failure."""
    try:
        return {c for c in adapter.obsoletes() if isinstance(c, str) and c.startswith("HP:")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("adapter.obsoletes() failed (%s); falling back to label heuristic", exc)
        return set()


def _exact_synonyms(adapter, curie: str) -> set[str]:
    """Lower-cased exact synonyms of ``curie`` (``oio:hasExactSynonym``), or empty."""
    try:
        meta = adapter.entity_metadata_map(curie)
    except Exception:  # noqa: BLE001
        return set()
    out: set[str] = set()
    for key in ("oio:hasExactSynonym", "IAO:0000118"):
        for v in meta.get(key, []) or []:
            out.add(str(v).lower())
    return out


# ----------------------------------------------------------------- subject resolution


def _resolve_data_dict(table: str, data_root: Path) -> Path | None:
    """Find ``<table>.json`` anywhere under ``data_root`` (table stems are unique)."""
    matches = sorted(data_root.glob(f"**/{table}.json"))
    return matches[0] if len(matches) == 1 else None


# ------------------------------------------------------------------------- validation


def _check_row(
    row: dict[str, str],
    fname: str,
    file_prefixes: set[str],
    seen: set[tuple[str, str, str]],
) -> Iterable[Finding]:
    subj = row.get("subject_id", "").strip()
    pred = row.get("predicate_id", "").strip()
    obj = row.get("object_id", "").strip()
    ident = subj or "<no subject_id>"

    def err(code: str, message: str) -> Finding:
        return Finding(fname, ident, "error", code, message)

    for col in REQUIRED_COLUMNS:
        if not row.get(col, "").strip():
            yield err("missing-field", f"empty required column {col!r}")

    if subj and not subj.startswith("b2ai:"):
        yield err("bad-subject", f"subject_id must be a b2ai: CURIE, got {subj!r}")
    elif subj and "." not in subj.split(":", 1)[1]:
        yield err("malformed-subject", f"b2ai subject must be b2ai:<table>.<column>: {subj!r}")
    if pred and pred not in ALLOWED_PREDICATES:
        yield err("bad-predicate", f"predicate_id {pred!r} not in {sorted(ALLOWED_PREDICATES)}")
    if obj and not obj.startswith("HP:"):
        yield err("bad-object", f"object_id must be an HP: CURIE, got {obj!r}")

    # self-containment: every CURIE used must be declared in this file's own curie_map
    for curie in (subj, pred, obj, row.get("mapping_justification", "").strip()):
        if curie and ":" in curie:
            prefix = curie.split(":", 1)[0]
            if prefix not in file_prefixes:
                yield err("unknown-prefix", f"prefix {prefix!r} not in the file's curie_map")

    conf = row.get("confidence", "").strip()
    if conf:
        try:
            val = float(conf)
            if not 0.0 <= val <= 1.0:
                yield err("bad-confidence", f"confidence {val} out of [0,1]")
        except ValueError:
            yield err("bad-confidence", f"confidence {conf!r} is not a number")

    if subj and pred and obj:
        triple = (subj, pred, obj)
        if triple in seen:
            yield err("duplicate", f"duplicate mapping {triple}")
        seen.add(triple)


def _check_subject_exists(
    row: dict[str, str], fname: str, data_root: Path, result: ValidationResult
) -> Iterable[Finding]:
    subj = row.get("subject_id", "").strip()
    if not subj.startswith("b2ai:") or "." not in subj:
        return  # malformed subjects are flagged structurally in _check_row
    local = subj.split(":", 1)[1]
    table, column = local.split(".", 1)  # first dot: table stem never contains a dot
    dict_path = _resolve_data_dict(table, data_root)
    if dict_path is None:
        result.subjects_unresolved += 1
        yield Finding(
            fname, subj, "warning", "table-not-found",
            f"no unique {table}.json under {data_root}; subject left unverified",
        )
        return
    columns = load_data_dict(dict_path)
    if column not in columns:
        yield Finding(
            fname, subj, "error", "unknown-column",
            f"column {column!r} not found in {dict_path.name}",
        )


def _check_object_in_hpo(
    row: dict[str, str], fname: str, adapter, obsolete_ids: set[str]
) -> Iterable[Finding]:
    subj = row.get("subject_id", "").strip() or "<no subject_id>"
    obj = row.get("object_id", "").strip()
    declared = row.get("object_label", "").strip()
    if not obj.startswith("HP:"):
        return  # structural check already flagged it
    label = adapter.label(obj)
    if label is None:
        yield Finding(
            fname, subj, "error", "hallucinated-term",
            f"{obj} does not exist in the loaded HPO release",
        )
        return
    # Deprecation via the authoritative owl:deprecated flag, with the label convention as a
    # redundant backstop (some deprecated terms keep a non-"obsolete " label, e.g. HP:0007815).
    if obj in obsolete_ids or label.lower().startswith("obsolete"):
        yield Finding(
            fname, subj, "error", "obsolete-term",
            f"{obj} is obsolete/deprecated in HPO ({label!r})",
        )
        return
    if not declared:
        yield Finding(
            fname, subj, "warning", "missing-object-label",
            f"{obj} has no object_label; label drift cannot be checked (HPO label {label!r})",
        )
        return
    if declared.lower() == label.lower():
        return
    if declared.lower() in _exact_synonyms(adapter, obj):
        yield Finding(
            fname, subj, "warning", "noncanonical-label",
            f"{obj} object_label {declared!r} is an exact synonym, not the primary label {label!r}",
        )
    else:
        yield Finding(
            fname, subj, "error", "label-mismatch",
            f"{obj} object_label {declared!r} != HPO label {label!r} (and not an exact synonym)",
        )


def validate_paths(
    paths: Iterable[Path],
    data_root: Path | None = None,
    check_ontology: bool | None = None,
) -> ValidationResult:
    """Validate SSSOM files.

    ``check_ontology``: None = auto (use oaklib if present), True = require it, False = skip.
    Structural and subject checks always run; only the HPO layer depends on the backend.
    """
    result = ValidationResult()
    adapter = obsolete_ids = None
    if check_ontology is not False:
        adapter = _get_hp_adapter()
        if adapter is None and check_ontology is True:
            result.findings.append(
                Finding("<config>", "-", "error", "no-ontology-backend",
                        "oaklib/HPO backend required (--strict-ontology) but unavailable")
            )
        elif adapter is not None:
            obsolete_ids = _obsolete_ids(adapter)
            result.hpo_version = _adapter_hpo_version(adapter)
    result.ontology_checked = adapter is not None
    result.subjects_checked = data_root is not None

    seen: set[tuple[str, str, str]] = set()  # cross-file duplicate detection
    for path in paths:
        fname = path.name
        try:
            metadata, rows = parse_sssom(path)
        except MetadataError as exc:
            result.findings.append(
                Finding(fname, "-", "error", "bad-metadata", f"unparseable SSSOM header: {exc}")
            )
            continue
        file_prefixes = set((metadata.get("curie_map") or {}).keys())
        if not file_prefixes:
            result.findings.append(
                Finding(fname, "-", "error", "no-curie-map", "file has no curie_map metadata")
            )
        result.findings.extend(_check_version(metadata, fname, result.hpo_version))
        result.n_rows += len(rows)
        for row in rows:
            result.findings.extend(_check_row(row, fname, file_prefixes, seen))
            if data_root is not None:
                result.findings.extend(_check_subject_exists(row, fname, data_root, result))
            if adapter is not None:
                result.findings.extend(
                    _check_object_in_hpo(row, fname, adapter, obsolete_ids or set())
                )
    return result


def _check_version(metadata: dict[str, Any], fname: str, loaded: str | None) -> Iterable[Finding]:
    """Warn if the loaded HPO release differs from the file's declared ``object_source_version``."""
    declared = str(metadata.get("object_source_version") or "").strip()
    if not declared or not loaded:
        return
    m = _RELEASE_DATE.search(declared)
    declared_date = m.group(1) if m else declared
    if declared_date != loaded:
        yield Finding(
            fname, "-", "warning", "hpo-version-mismatch",
            f"validated against HPO {loaded} but file declares object_source_version "
            f"{declared!r}; label/obsolescence results reflect {loaded}",
        )


def default_mapping_files(repo_root: Path | None = None) -> list[Path]:
    """The shipped SSSOM files under ``mappings/``."""
    root = repo_root or Path(__file__).resolve().parents[3]
    return sorted((root / "mappings").glob("*.sssom.tsv"))
