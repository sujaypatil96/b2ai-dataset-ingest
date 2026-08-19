"""Preflight contract-validation for the Bridge2AI-Voice layout.

The reader is deliberately tolerant — it degrades rather than crashes — which is the right
behavior for a batch ingest but hides shape drift. ``validate`` is the loud counterpart: it
checks, *before* any phenopacket is written, that each table on disk matches what its mapping
config and companion data dictionary promise. Run it the moment real data lands.

Every check reads only *headers, dictionary keys, and aggregate cell counts* — never raw cell
values or ``participant_id`` — so it is safe to run against the HIPAA-sensitive real dataset
and to print/log its output. The one place cells are touched (choice-coverage) reports counts
only: how many answers resolved, and how many *distinct* answers did not — not what they were.

Findings are graded:

- ``error``   — a contract violation that will silently corrupt or empty output (missing table,
                unresolved session column, a mapped column absent from the header, an
                unreadable data-dict envelope). The CLI exits non-zero if any are present.
- ``warning`` — a mismatch worth a human's eyes that the reader can still limp through
                (dict keys != header, low choice-coverage, an unmapped table on disk).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from b2ai_dataset_ingest.mapping.engine import MappingEngine
from b2ai_dataset_ingest.mapping.loaders import (
    is_placeholder,
    load_data_dict,
    load_mapping,
)
from b2ai_dataset_ingest.sources.voice.reader import (
    _read_tsv_header_and_rows,
    _resolve_session_column,
    _session_columns,
)


@dataclass
class Finding:
    level: str  # "error" | "warning"
    table: str
    message: str


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)
    tables_checked: list[str] = field(default_factory=list)

    def error(self, table: str, message: str) -> None:
        self.findings.append(Finding("error", table, message))

    def warning(self, table: str, message: str) -> None:
        self.findings.append(Finding("warning", table, message))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    def render(self) -> str:
        lines = [f"Validated {len(self.tables_checked)} table(s)."]
        for finding in self.findings:
            marker = "ERROR" if finding.level == "error" else "warn "
            lines.append(f"  [{marker}] {finding.table}: {finding.message}")
        lines.append(
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)."
            if self.findings
            else "No issues found."
        )
        return "\n".join(lines)


def validate_voice(root: Path, config_dir: Path) -> ValidationReport:
    """Validate the on-disk voice layout at ``root`` against configs in ``config_dir``."""
    report = ValidationReport()
    _validate_demographics(root, config_dir, report)
    _validate_diagnosis(root, config_dir, report)
    _validate_questionnaires(root, config_dir, report)
    return report


# -- per-subdir checks --
def _validate_demographics(root: Path, config_dir: Path, report: ValidationReport) -> None:
    path = config_dir / "demographics.yaml"
    if not path.exists():
        return
    mapping = load_mapping(path)
    table = mapping.get("table", "demographics")
    tsv = root / "demographics" / f"{table}.tsv"
    header, _ = _read_tsv_header_and_rows(tsv)
    if header is None:
        report.error(table, f"table file not found ({tsv.name})")
        return
    report.tables_checked.append(table)
    _check_dict_vs_header(tsv, header, table, report)
    _check_alternative_columns_present(mapping.get("columns") or {}, header, table, report)


def _validate_diagnosis(root: Path, config_dir: Path, report: ValidationReport) -> None:
    path = config_dir / "diagnosis.yaml"
    diag_dir = root / "diagnosis"
    if not path.exists() or not diag_dir.is_dir():
        return
    mapping = load_mapping(path)
    conditions = mapping.get("conditions") or {}
    on_disk = {p.stem for p in diag_dir.glob("*.tsv")}
    configured = set(conditions) | {"control"}
    for extra in sorted(on_disk - configured):
        report.warning(f"diagnosis/{extra}", "condition file on disk has no config entry")
    for missing in sorted(configured - on_disk - {"control"}):
        report.warning(f"diagnosis/{missing}", "configured condition has no file on disk")
    unresolved = sorted(
        name for name, term in conditions.items() if is_placeholder(term) and name in on_disk
    )
    if unresolved:
        report.warning(
            "diagnosis",
            f"{len(unresolved)} condition(s) unresolved (no Disease): {', '.join(unresolved)}",
        )
    for tsv in sorted(diag_dir.glob("*.tsv")):
        report.tables_checked.append(f"diagnosis/{tsv.stem}")
        header, _ = _read_tsv_header_and_rows(tsv)
        if header and "participant_id" not in header:
            report.error(f"diagnosis/{tsv.stem}", "no participant_id column")


def _validate_questionnaires(root: Path, config_dir: Path, report: ValidationReport) -> None:
    data_dir = root / "questionnaire"
    cfg_dir = config_dir / "questionnaire"
    if not data_dir.is_dir():
        return
    configs: dict[str, tuple[Path, dict]] = {}
    if cfg_dir.is_dir():
        for cfg_path in sorted(cfg_dir.glob("*.yaml")):
            m = load_mapping(cfg_path)
            configs[m.get("table", cfg_path.stem)] = (cfg_path, m)
    for tsv in sorted(data_dir.glob("*.tsv")):
        table = tsv.stem
        entry = configs.get(table)
        if entry is None:
            report.warning(table, "questionnaire on disk has no mapping config (not ingested)")
            continue
        _, mapping = entry
        header, rows = _read_tsv_header_and_rows(tsv)
        if header is None:
            report.error(table, f"table file not found ({tsv.name})")
            continue
        report.tables_checked.append(table)
        _check_dict_vs_header(tsv, header, table, report)
        # Session key must resolve, else every visit collapses (or emits un-merged).
        candidates = _session_columns(mapping)
        if _resolve_session_column({c: "" for c in header}, candidates) is None:
            report.error(table, f"none of session_columns {candidates} present in header")
        mapped = list(mapping.get("items") or {})
        score = mapping.get("score") or {}
        if score.get("source_column"):
            mapped.append(score["source_column"])
        _check_columns_present(mapped, header, table, report)
        _check_choice_coverage(tsv, mapping, rows, table, report)


# -- shared checks --
def _check_dict_vs_header(
    tsv: Path, header: list[str], table: str, report: ValidationReport
) -> None:
    """The documented invariant: data-dict keys == TSV columns. Report set differences only."""
    data_dict = load_data_dict(tsv.with_suffix(".json"))
    if not data_dict:
        if tsv.with_suffix(".json").exists():
            report.error(table, "companion data dict present but its envelope was unrecognized")
        return
    dict_keys, cols = set(data_dict), set(header)
    only_dict, only_cols = dict_keys - cols, cols - dict_keys
    if only_dict or only_cols:
        report.warning(
            table,
            f"dict/header mismatch: {len(only_dict)} key(s) only in dict, "
            f"{len(only_cols)} column(s) only in TSV",
        )


def _check_columns_present(
    mapped: Iterable[str], header: list[str], table: str, report: ValidationReport
) -> None:
    missing = [c for c in mapped if c not in header]
    if missing:
        report.error(table, f"mapped column(s) absent from header: {', '.join(missing)}")


def _check_alternative_columns_present(
    columns: dict[str, dict], header: list[str], table: str, report: ValidationReport
) -> None:
    """Columns sharing an IR target are *alternatives*: at least one must be present.

    Demographics maps two source columns to ``Individual.sex`` — a preferred column and a
    fallback — because releases differ in which they ship (the real b2aiprep tables carry
    both; the public synthetic tables carry only ``sex_assigned_at_birth``). Requiring every
    mapped column to exist would make one of those two releases fail validation no matter
    which single column the config named. The reader resolves the value by declaration
    order, so a release shipping either column is fine; only a target with *no* source
    column at all is a contract error.
    """
    by_target: dict[str, list[str]] = {}
    for column, spec in columns.items():
        by_target.setdefault((spec or {}).get("target", ""), []).append(column)
    for target, cols in sorted(by_target.items()):
        if not any(c in header for c in cols):
            alternatives = ", ".join(sorted(cols))
            report.error(table, f"no source column for {target or '?'} (tried: {alternatives})")


def _check_choice_coverage(
    tsv: Path, mapping: dict, rows: list[dict[str, str]], table: str, report: ValidationReport
) -> None:
    """Aggregate-only: per item, how many answers resolve, and how many DISTINCT do not.

    Never emits the answer values themselves — only counts — so it is safe on real data.
    """
    data_dict = load_data_dict(tsv.with_suffix(".json"))
    engine = MappingEngine(mapping)
    for column in mapping.get("items") or {}:
        resolved = unresolved = 0
        distinct_unresolved: set[str] = set()
        for row in rows:
            answer = (row.get(column) or "").strip()
            if not answer:
                continue
            if engine.ordinal_value(column, answer, data_dict) is None:
                unresolved += 1
                distinct_unresolved.add(answer)
            else:
                resolved += 1
        if unresolved:
            report.warning(
                table,
                f"{column}: {resolved}/{resolved + unresolved} answers resolved, "
                f"{len(distinct_unresolved)} distinct unresolved value(s)",
            )
