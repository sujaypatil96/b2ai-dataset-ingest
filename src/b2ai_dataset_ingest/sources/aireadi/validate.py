"""Preflight contract-validation for the AI-READI OMOP layout.

The counterpart to :mod:`sources.voice.validate`, and it exists for the same reason: the
reader degrades rather than crashes, which is right for a batch ingest and hides shape
drift. For an OMOP release the drift that matters is different, so the checks are too:

- a required table or column is missing;
- an item key the config maps is absent from the release (a config naming a variable the
  data does not ship emits nothing, silently);
- an item key in the data has no config entry (present but not ingested);
- a field is *fully redacted* — a release may ship ``gender_concept_id = 0`` on every row,
  and a run of all-``UNKNOWN_SEX`` subjects must not look like success;
- a declared unit disagrees with the unit the data carries where the data carries one.

**Why an item-key inventory is not PHI.** OMOP is EAV, so what Voice keeps in a *header*
(``nervous_anxious``) AI-READI keeps in a *cell* (``observation_source_value``). The set of
distinct ``(item key)`` values in a long table is definitionally the column list of the
equivalent wide table — it is schema, not participant data. Refusing to inventory it would
mean the validator could check nothing at all, which is the worse privacy outcome.

Everything reported is a variable name, a column name, or a count. Never reported: a
``person_id``, a ``value_as_*`` cell, a ``range_*`` bound, or a date. Per-item counts below
:data:`SMALL_CELL` print as ``<5``: a rare condition can have a single-digit count, and a
count of 1 plus outside knowledge is a small-cell disclosure.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from b2ai_dataset_ingest.mapping.loaders import is_placeholder, load_mapping
from b2ai_dataset_ingest.mapping.omop import as_number, is_blank, item_key
from b2ai_dataset_ingest.mapping.redcap import (
    ExcelSupportMissing,
    cell_text,
    checkbox_column,
    locate_files,
    looks_like_datetime,
    normalize_id,
    read_header,
    stream_rows,
)

#: Counts at or below this print as "<5" rather than the exact number.
SMALL_CELL = 5

#: Columns a finding may name. Anything outside this is a value, not a vocabulary.
REPORTABLE_COLUMNS = frozenset(
    {
        "person_id",  # named as a *column*, never as a value
        "condition_source_value",
        "measurement_source_value",
        "observation_source_value",
        "procedure_source_value",
        "gender_concept_id",
        "race_concept_id",
        "ethnicity_concept_id",
        "unit_concept_id",
        "unit_source_value",
        "qualifier_concept_id",
        "visit_occurrence_id",
    }
)


@dataclass
class Finding:
    level: str  # "error" | "warning" | "info"
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

    def info(self, table: str, message: str) -> None:
        self.findings.append(Finding("info", table, message))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    def render(self) -> str:
        lines = [f"Validated {len(self.tables_checked)} table(s)."]
        markers = {"error": "ERROR", "warning": "warn ", "info": "info "}
        for finding in self.findings:
            lines.append(f"  [{markers[finding.level]}] {finding.table}: {finding.message}")
        lines.append(
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)."
            if self.findings
            else "No issues found."
        )
        return "\n".join(lines)


def count(n: int) -> str:
    """Render a count, suppressing small cells."""
    return f"<{SMALL_CELL}" if 0 < n < SMALL_CELL else str(n)


def validate_aireadi(
    root: Path,
    config_dir: Path,
    strict_coverage: bool = False,
    protected: Path | None = None,
) -> ValidationReport:
    """Validate the on-disk AI-READI layout at ``root`` against configs in ``config_dir``.

    ``strict_coverage`` asserts that this release is *complete*, promoting two findings from
    warning to error: a configured item the release does not ship, and a whole table the
    release does not ship. Both are off by default because completeness is a property of the
    release rather than a contract violation — a small fixture legitimately exercises a
    handful of items, and the VUMC synthetic release ships two of the six tables and still
    ingests correctly. Turn it on against a full release, where a config naming a variable or
    a table the data does not have silently emits nothing.

    What is an error *regardless*: a table that is present but malformed — a missing
    ``person_id``, a missing key column, an unreadable header. Those are contract violations
    at any coverage level.

    ``protected`` names the directory holding the protected supplement's REDCap exports (sex,
    race/ethnicity, medications). Those are checked on the same PHI terms — see
    :func:`_validate_protected`.
    """
    report = ValidationReport()
    _validate_participants(root, config_dir, report, strict_coverage)
    _validate_person(root, config_dir, report, strict_coverage)
    _validate_visits(root, report, strict_coverage)
    _validate_long_table(
        root, config_dir, report, "conditions.yaml", "conditions", strict_coverage
    )
    _validate_measurements(root, config_dir, report, strict_coverage)
    _check_root_looks_like_a_release(root, report)
    if protected is not None:
        _validate_protected(root, config_dir, Path(protected), report)
    return report


def _check_root_looks_like_a_release(root: Path, report: ValidationReport) -> None:
    """Finding *nothing* is a wrong root far more often than an empty release.

    Every per-table check reports its own table as absent, so pointing at the wrong
    directory produces five identical "not present in this release" lines and no hint that
    the release is fine and the path is not. Distinguishing the two costs one check and
    saves the reader guessing.

    The specific trap this exists for: an AI-READI download nests everything under a
    ``dataset/`` wrapper, so the root a user naturally passes is one level above the one the
    reader wants.

    ``clinical_data/`` sitting directly under the root is what tells the two apart. If it is
    there, the root is right and the release really is empty — which is a legitimate state
    the reader degrades through, so saying "wrong root" would be a lie. Only its absence,
    with nothing found, means the caller is almost certainly one directory too high.
    """
    if report.tables_checked or (root / "clinical_data").is_dir():
        return
    report.error(
        "-",
        f"no tables found under {root.name or root}/ — this usually means the root is wrong "
        f"rather than that the release is empty. The reader expects participants.tsv and "
        f"clinical_data/ directly beneath it; an AI-READI download nests those under a "
        f"dataset/ wrapper, so try the directory that contains clinical_data/.",
    )
    for candidate in ("dataset", "data"):
        nested = root / candidate / "clinical_data"
        if nested.is_dir():
            report.info("-", f"found clinical_data/ at {root.name}/{candidate}/ — try that root")


# -- per-table checks --------------------------------------------------------------
def _validate_participants(
    root: Path, config_dir: Path, report: ValidationReport, strict_coverage: bool = False
) -> None:
    mapping = _load(config_dir / "participants.yaml")
    if mapping is None:
        return
    path = root / mapping.get("file", "participants.tsv")
    header, rows = _read(path, mapping.get("delimiter", "\t"))
    if header is None:
        _note_missing_table(report, "participants", path.name, strict_coverage)
        return
    report.tables_checked.append("participants")
    for column in list(mapping.get("columns") or {}) + [mapping.get("id_column", "person_id")]:
        if column not in header:
            report.error("participants", f"mapped column absent from header: {column}")
    report.info("participants", f"{count(len(rows))} participant row(s)")


def _validate_person(
    root: Path, config_dir: Path, report: ValidationReport, strict_coverage: bool = False
) -> None:
    mapping = _load(config_dir / "person.yaml")
    if mapping is None:
        return
    path = root / "clinical_data" / "person.csv"
    header, rows = _read(path, ",")
    if header is None:
        _note_missing_table(report, "person", "person.csv", strict_coverage)
        return
    report.tables_checked.append("person")
    # A fully-redacted mapped column is the finding that stops a run of all-UNKNOWN_SEX
    # subjects from reading as a clean run.
    for column in mapping.get("columns") or {}:
        if column not in header:
            report.error("person", f"mapped column absent from header: {column}")
            continue
        filled = sum(1 for r in rows if not is_blank(r.get(column, ""), ("", " ", "0")))
        if rows and filled == 0:
            report.warning(
                "person",
                f"{column} is fully redacted in this release ({len(rows)}/{len(rows)} rows "
                f"blank or 0); Individual.sex will be unset",
            )


def _validate_visits(
    root: Path, report: ValidationReport, strict_coverage: bool = False
) -> None:
    header, rows = _read(root / "clinical_data" / "visit_occurrence.csv", ",")
    if header is None:
        _note_missing_table(report, "visit_occurrence", "visit_occurrence.csv", strict_coverage)
        return
    report.tables_checked.append("visit_occurrence")
    for column in ("visit_occurrence_id", "person_id"):
        if column not in header:
            report.error("visit_occurrence", f"required column absent from header: {column}")
    report.info("visit_occurrence", f"{count(len(rows))} visit row(s)")


def _validate_long_table(
    root: Path,
    config_dir: Path,
    report: ValidationReport,
    config_name: str,
    block: str,
    strict_coverage: bool = False,
) -> None:
    mapping = _load(config_dir / config_name)
    if mapping is None:
        return
    table = mapping.get("table", "?")
    header, rows = _read(root / "clinical_data" / f"{table}.csv", mapping.get("delimiter", ","))
    if header is None:
        _note_missing_table(report, table, f"{table}.csv", strict_coverage)
        return
    report.tables_checked.append(table)
    key_column = mapping.get("key_column", f"{table}_source_value")
    for column in (key_column, mapping.get("id_column", "person_id")):
        if column not in header:
            report.error(table, f"required column absent from header: {column}")
            return
    configured = mapping.get(block) or {}
    _compare_items(rows, key_column, configured, table, report, strict_coverage)


def _validate_measurements(
    root: Path, config_dir: Path, report: ValidationReport, strict_coverage: bool = False
) -> None:
    configs = sorted((config_dir / "measurement").glob("*.yaml"))
    if not configs:
        return
    measures: dict[str, Any] = {}
    for path in configs:
        measures.update((_load(path) or {}).get("measures") or {})
    header, rows = _read(root / "clinical_data" / "measurement.csv", ",")
    if header is None:
        _note_missing_table(report, "measurement", "measurement.csv", strict_coverage)
        return
    report.tables_checked.append("measurement")
    if "measurement_source_value" not in header:
        report.error("measurement", "required column absent from header: measurement_source_value")
        return
    _compare_items(
        rows, "measurement_source_value", measures, "measurement", report, strict_coverage
    )
    _check_declared_units(rows, measures, report)
    _check_laterality(rows, measures, report)


# -- shared checks -----------------------------------------------------------------
def _note_missing_table(
    report: ValidationReport, table: str, filename: str, strict_coverage: bool
) -> None:
    """An absent table is a completeness finding, not a contract violation.

    The reader degrades to ``tables_missing`` and still emits, which is the right behaviour
    for a partial release — the VUMC synthetic set ships two of the six tables and ingests
    correctly. So this warns by default and errors only under ``--strict-coverage``, which is
    where the caller is asserting the release is complete. Handling every absent table the
    same way is the point: participants/person/visit previously disagreed with each other.
    """
    note = report.error if strict_coverage else report.warning
    note(table, f"table not present in this release ({filename})")



def _compare_items(
    rows: list[dict[str, str]],
    key_column: str,
    configured: dict[str, Any],
    table: str,
    report: ValidationReport,
    strict_coverage: bool = False,
) -> None:
    """Set-difference the item keys on disk against the item keys the config maps."""
    on_disk = Counter(item_key(r.get(key_column, "")) for r in rows)
    on_disk.pop("", None)
    unmapped = sorted(set(on_disk) - set(configured))
    if unmapped:
        report.warning(
            table,
            f"{len(unmapped)} item(s) on disk have no config entry (not ingested): "
            + ", ".join(unmapped[:12])
            + (" ..." if len(unmapped) > 12 else ""),
        )
    missing = sorted(set(configured) - set(on_disk))
    if missing:
        # A config naming a variable the release does not ship emits nothing, silently —
        # worth an error against a full release, but expected for a fixture or a partial one.
        note = report.error if strict_coverage else report.warning
        note(
            table,
            f"{len(missing)} configured item(s) absent from this release: "
            + ", ".join(missing[:12])
            + (" ..." if len(missing) > 12 else ""),
        )
    placeholders = sorted(
        name for name, spec in configured.items() if is_placeholder(_term_of(spec))
    )
    if placeholders:
        report.warning(
            table,
            f"{len(placeholders)} configured item(s) unresolved (no output): "
            + ", ".join(placeholders),
        )


def _term_of(spec: Any) -> Any:
    """A conditions entry IS the term; a measures entry carries it under ``assay``."""
    return spec.get("assay", spec) if isinstance(spec, dict) and "assay" in spec else spec


def _check_declared_units(
    rows: list[dict[str, str]], measures: dict[str, Any], report: ValidationReport
) -> None:
    """Where the data carries a unit string, it must agree with the config's declared one."""
    seen: dict[str, set[str]] = {}
    for row in rows:
        key = item_key(row.get("measurement_source_value", ""))
        source_unit = (row.get("unit_source_value") or "").strip()
        if key in measures and source_unit and source_unit != "N/A":
            seen.setdefault(key, set()).add(source_unit)
    for key, units in sorted(seen.items()):
        declared = ((measures[key] or {}).get("unit") or {}).get("label")
        mismatched = {u for u in units if u != declared}
        if declared and mismatched:
            report.warning(
                "measurement",
                f"{key}: config declares unit {declared!r} but the data carries "
                f"{sorted(mismatched)!r}",
            )


def _check_laterality(
    rows: list[dict[str, str]], measures: dict[str, Any], report: ValidationReport
) -> None:
    """Cross-check the config's declared body_site against the qualifier column.

    The column is only a cross-check: six autorefraction items are per-eye by name and carry
    no qualifier at all, so its absence is expected and is reported as info, not a warning.
    """
    qualifiers: dict[str, set[str]] = {}
    for row in rows:
        key = item_key(row.get("measurement_source_value", ""))
        qualifier = (row.get("qualifier_source_value") or "").strip()
        if key in measures and qualifier:
            qualifiers.setdefault(key, set()).add(qualifier)
    sided = {k for k, spec in measures.items() if (spec or {}).get("body_site")}
    silent = sorted(k for k in sided if k not in qualifiers)
    if silent:
        report.info(
            "measurement",
            f"{len(silent)} item(s) declare a body_site the data does not qualify "
            f"(expected: per-eye by name): " + ", ".join(silent[:8]),
        )
    for key in sorted(sided & set(qualifiers)):
        declared = (measures[key]["body_site"] or {}).get("label", "")
        observed = {q.lower() for q in qualifiers[key]}
        if declared and declared.lower() not in observed:
            report.warning(
                "measurement",
                f"{key}: config declares body_site {declared!r} but the data qualifies "
                f"{sorted(qualifiers[key])!r}",
            )


# -- IO ------------------------------------------------------------------------------
def _load(path: Path) -> dict[str, Any] | None:
    return load_mapping(path) if path.exists() else None


def _read(path: Path, delimiter: str) -> tuple[list[str] | None, list[dict[str, str]]]:
    """Read a table into (header, rows). ``header`` is None only when the file is absent."""
    if not path.exists():
        return None, []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        rows = list(reader)
        header = list(reader.fieldnames) if reader.fieldnames else []
    return header, rows


# -- the protected supplement (REDCap exports) ---------------------------------------------
#
# Same terms as the OMOP checks: column names, choice codes and watchlist ingredient names are
# vocabulary; everything else is a count, small cells suppressed. The free-text columns are
# named only as *present and unread*; nothing about their contents is summarised, not even a
# fill count.


def _validate_protected(
    root: Path, config_dir: Path, protected_dir: Path, report: ValidationReport
) -> None:
    configs = sorted((config_dir / "protected").glob("*.yaml"))
    if not configs:
        report.warning(
            "protected", f"--protected given, but {config_dir}/protected/ holds no *.yaml"
        )
        return
    cohort = _cohort_ids(root, config_dir)
    for path in configs:
        mapping = _load(path) or {}
        table = str(mapping.get("table", path.stem))
        pattern = str(mapping.get("file_glob", ""))
        matches = locate_files(protected_dir, pattern)
        if len(matches) != 1:
            report.error(
                table,
                f"expected exactly one export matching {pattern!r} under "
                f"{protected_dir.name or protected_dir}/, found {len(matches)}",
            )
            continue
        report.tables_checked.append(table)
        try:
            header = read_header(matches[0], mapping.get("sheet"))
            rows = list(stream_rows(matches[0], mapping.get("sheet"), typed=True))
        except ExcelSupportMissing as exc:
            report.error(table, str(exc))
            continue
        if mapping.get("produces") == "TreatmentObservation":
            _check_medications(mapping, table, header, rows, cohort, report)
        else:
            _check_demographics(mapping, table, header, rows, cohort, report)


def _cohort_ids(root: Path, config_dir: Path) -> set[str] | None:
    """Every ``person_id`` the clinical tables establish, or None when no table is present.

    All tables, not only ``participants.tsv``: the reader creates a participant from any table
    that names one (a measurement-only participant still gets a packet), so the overlap check
    must use the same universe or it would call a matched row unmatched. Streams the id
    column only -- ``measurement.csv`` is the large one.
    """
    ids: set[str] = set()
    found = False
    mapping = _load(config_dir / "participants.yaml") or {}
    cohort_ids = _ids_in(
        root / mapping.get("file", "participants.tsv"),
        mapping.get("id_column", "person_id"),
        mapping.get("delimiter", "\t"),
    )
    if cohort_ids is not None:
        found, ids = True, ids | cohort_ids
    for table in ("person", "condition_occurrence", "measurement", "observation"):
        table_ids = _ids_in(root / "clinical_data" / f"{table}.csv", "person_id", ",")
        if table_ids is not None:
            found, ids = True, ids | table_ids
    return ids if found else None


def _ids_in(path: Path, column: str, delimiter: str) -> set[str] | None:
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as fh:
        ids = {normalize_id(row.get(column)) for row in csv.DictReader(fh, delimiter=delimiter)}
    ids.discard("")
    return ids


def _header_map(header: list[str]) -> dict[str, str]:
    return {name.lower(): name for name in header if name}


def _require(
    table: str, header_map: dict[str, str], wanted: list[str], report: ValidationReport
) -> None:
    for name in wanted:
        if name.lower() not in header_map:
            report.error(table, f"mapped column absent from header: {name}")


def _describe_header(
    table: str,
    header: list[str],
    documented: set[str],
    dropped: dict[str, Any],
    header_map: dict[str, str],
    report: ValidationReport,
) -> None:
    """Every export column is either mapped or listed as deliberately unread, and says why."""
    undocumented = [name for name in header if name and name.lower() not in documented]
    if undocumented:
        report.warning(
            table,
            f"{len(undocumented)} column(s) in the export are described by neither the "
            "mapping nor dropped_columns: "
            + ", ".join(undocumented[:12])
            + (" ..." if len(undocumented) > 12 else ""),
        )
    absent = sorted(str(c) for c in dropped if str(c).lower() not in header_map)
    if absent:
        report.info(
            table, f"{len(absent)} documented column(s) not in this export: " + ", ".join(absent)
        )
    free_text = sorted(
        str(c)
        for c, why in dropped.items()
        if "free text" in str(why).lower() and str(c).lower() in header_map
    )
    if free_text:
        report.info(
            table,
            f"{len(free_text)} free-text column(s) present and never read: " + ", ".join(free_text),
        )


def _overlap(
    table: str, ids: set[str], cohort: set[str] | None, report: ValidationReport, noun: str
) -> None:
    if cohort is None:
        report.info(table, "no clinical tables under the root; id overlap not checked")
        return
    unmatched = len(ids - cohort)
    if unmatched:
        report.warning(
            table,
            f"{count(unmatched)} supplement id(s) match no participant in the clinical tables "
            "(those rows are dropped: the supplement enriches, it never creates)",
        )
    report.info(
        table,
        f"{count(len(ids & cohort))} of {count(len(cohort))} cohort participant(s) have "
        f"{noun}; {count(len(cohort - ids))} have none",
    )


def _check_demographics(
    mapping: dict[str, Any],
    table: str,
    header: list[str],
    rows: list[dict[str, Any]],
    cohort: set[str] | None,
    report: ValidationReport,
) -> None:
    header_map = _header_map(header)
    id_column = str(mapping.get("id_column", "studyid"))
    columns: dict[str, Any] = mapping.get("columns") or {}
    groups: dict[str, Any] = mapping.get("checkbox_groups") or {}
    dropped: dict[str, Any] = mapping.get("dropped_columns") or {}
    refusals = {str(code) for code in (mapping.get("refusal_codes") or [])}
    checkbox_columns = [
        checkbox_column(group, code)
        for group, spec in groups.items()
        for code in ((spec or {}).get("choices") or {})
    ]
    required = [id_column, *columns, *checkbox_columns]
    _require(table, header_map, required, report)
    documented = {c.lower() for c in required} | {str(c).lower() for c in dropped}
    _describe_header(table, header, documented, dropped, header_map, report)

    id_actual = header_map.get(id_column.lower())
    ids = Counter(normalize_id(row.get(id_actual)) for row in rows) if id_actual else Counter()
    ids.pop("", None)
    report.info(table, f"{count(len(rows))} row(s), {count(len(ids))} distinct id(s)")
    duplicated = sum(1 for n in ids.values() if n > 1)
    if duplicated:
        report.warning(
            table,
            f"{count(duplicated)} id(s) appear on more than one row; the reader keeps the first",
        )
    _overlap(table, set(ids), cohort, report, "a demographics row")

    for column, spec in columns.items():
        actual = header_map.get(column.lower())
        if actual is None:
            continue
        keys = {str(k).lower() for k in ((spec or {}).get("value_map") or {})}
        outside = refused = 0
        for row in rows:
            text = normalize_id(row.get(actual))
            if not text:
                continue
            if text.lower() in keys:
                refused += text in refusals
            else:
                outside += 1
        if outside:
            report.warning(
                table,
                f"{column}: {count(outside)} value(s) outside the dictionary's code set "
                "(dropped by the reader)",
            )
        if refused:
            report.info(table, f"{column}: {count(refused)} refusal(s) leave the field unset")
    for column in checkbox_columns:
        actual = header_map.get(column.lower())
        if actual is None:
            continue
        bad = sum(1 for row in rows if cell_text(row.get(actual)) not in {"", "0", "1"})
        if bad:
            report.warning(table, f"{column}: {count(bad)} cell(s) are not 0/1")


def _check_medications(
    mapping: dict[str, Any],
    table: str,
    header: list[str],
    rows: list[dict[str, Any]],
    cohort: set[str] | None,
    report: ValidationReport,
) -> None:
    header_map = _header_map(header)
    id_column = str(mapping.get("id_column", "studyid"))
    instrument_column = mapping.get("instrument_column")
    instrument = mapping.get("instrument")
    instance_column = mapping.get("instance_column")
    agent: dict[str, Any] = mapping.get("agent") or {}
    code_column = str(agent.get("code_column", "rxnorm_code"))
    label_column = str(agent.get("label_column", "rxnorm_term"))
    pattern = re.compile(str(agent.get("pattern", r"^[0-9]{1,7}$")))
    route: dict[str, Any] = mapping.get("route") or {}
    dose: dict[str, Any] = mapping.get("dose") or {}
    frequency: dict[str, Any] = mapping.get("frequency") or {}
    dropped: dict[str, Any] = mapping.get("dropped_columns") or {}
    coded: list[tuple[str, dict[Any, Any]]] = [
        (str(route.get("column", "")), route.get("terms") or {}),
        (str(dose.get("unit_column", "")), dose.get("units") or {}),
        (str(frequency.get("column", "")), frequency.get("terms") or {}),
    ]
    dose_column = str(dose.get("value_column", ""))
    required = [
        name
        for name in [
            id_column,
            str(instrument_column or ""),
            str(instance_column or ""),
            code_column,
            label_column,
            dose_column,
            *[column for column, _ in coded],
        ]
        if name
    ]
    _require(table, header_map, required, report)
    documented = {c.lower() for c in required} | {str(c).lower() for c in dropped}
    _describe_header(table, header, documented, dropped, header_map, report)

    id_actual = header_map.get(id_column.lower())
    ids = Counter(normalize_id(row.get(id_actual)) for row in rows) if id_actual else Counter()
    ids.pop("", None)
    report.info(table, f"{count(len(rows))} row(s), {count(len(ids))} distinct id(s)")
    _overlap(table, set(ids), cohort, report, "a medication row")

    if instrument_column and instrument and header_map.get(str(instrument_column).lower()):
        actual = header_map[str(instrument_column).lower()]
        other = sum(1 for row in rows if cell_text(row.get(actual)) not in {"", str(instrument)})
        if other:
            report.warning(
                table, f"{count(other)} row(s) belong to another instrument and are skipped"
            )
    if instance_column and id_actual and header_map.get(str(instance_column).lower()):
        actual = header_map[str(instance_column).lower()]
        pairs = Counter(
            (normalize_id(row.get(id_actual)), normalize_id(row.get(actual))) for row in rows
        )
        duplicated = sum(1 for n in pairs.values() if n > 1)
        if duplicated:
            report.warning(
                table,
                f"{count(duplicated)} (id, instance) pair(s) appear more than once; the reader "
                "keeps the first",
            )

    code_actual = header_map.get(code_column.lower())
    label_actual = header_map.get(label_column.lower())
    if code_actual and label_actual:
        blank = malformed = 0
        terms_by_code: dict[str, set[str]] = {}
        codes_by_term: dict[str, set[str]] = {}
        for row in rows:
            code = normalize_id(row.get(code_actual))
            term = cell_text(row.get(label_actual)).lower()
            if not code:
                blank += 1
                continue
            if not pattern.match(code):
                malformed += 1
                continue
            if term:
                terms_by_code.setdefault(code, set()).add(term)
                codes_by_term.setdefault(term, set()).add(code)
        if blank:
            report.info(table, f"{count(blank)} row(s) carry no RxNorm code and emit no agent")
        if malformed:
            report.warning(
                table, f"{count(malformed)} row(s) carry an RxNorm code that is not a bare RXCUI"
            )
        multi_terms = sum(1 for terms in terms_by_code.values() if len(terms) > 1)
        multi_codes = sum(1 for codes in codes_by_term.values() if len(codes) > 1)
        if multi_terms:
            report.warning(
                table,
                f"{count(multi_terms)} RxNorm code(s) carry more than one distinct term; the "
                "reader keeps each row's own term, but a code should name one concept",
            )
        else:
            report.info(
                table, f"{count(len(terms_by_code))} distinct RxNorm code(s), each with one term"
            )
        if multi_codes:
            report.info(table, f"{count(multi_codes)} term(s) appear under more than one code")

    for column, terms in coded:
        actual = header_map.get(column.lower()) if column else None
        if actual is None:
            continue
        keys = {str(k).lower(): k for k in terms}
        outside = policy = 0
        for row in rows:
            text = normalize_id(row.get(actual))
            if not text:
                continue
            key = keys.get(text.lower())
            if key is None:
                outside += 1
            elif terms[key] is None:
                policy += 1
        if outside:
            report.warning(
                table,
                f"{column}: {count(outside)} value(s) not in the config's code set (dropped by "
                "the reader)",
            )
        if policy:
            report.info(
                table,
                f"{column}: {count(policy)} value(s) map to no term by design (Other / no NCIT "
                "term); that slot is left unset",
            )

    dose_actual = header_map.get(dose_column.lower()) if dose_column else None
    if dose_actual:
        dated = other = 0
        for row in rows:
            raw = row.get(dose_actual)
            text = cell_text(raw)
            if not text or as_number(text) is not None:
                continue
            if looks_like_datetime(raw):
                dated += 1
            else:
                other += 1
        if dated:
            report.warning(
                table,
                f"{dose_column}: {count(dated)} cell(s) are typed as dates -- Excel "
                "auto-converted free text such as '1-2' on entry; the dose is dropped and the "
                "medication kept",
            )
        if other:
            report.info(table, f"{dose_column}: {count(other)} other non-numeric cell(s) dropped")

    watchlist = [str(item) for item in (mapping.get("otc_watchlist") or [])]
    if watchlist and label_actual and id_actual:
        patterns = [
            (item, re.compile(r"\b" + re.escape(item.lower()) + r"\b")) for item in watchlist
        ]
        hits: Counter = Counter()
        people: set[str] = set()
        for row in rows:
            term = cell_text(row.get(label_actual)).lower()
            if not term:
                continue
            matched = False
            for item, regex in patterns:
                if regex.search(term):
                    hits[item] += 1
                    matched = True
            if matched:
                people.add(normalize_id(row.get(id_actual)))
        declared = str(mapping.get("drug_type") or "UNKNOWN_DRUG_TYPE")
        total = sum(hits.values())
        if total:
            detail = ", ".join(f"{item}={count(n)}" for item, n in hits.most_common())
            report.info(
                table,
                f"over-the-counter watchlist: {count(total)} row(s) across "
                f"{count(len(people))} participant(s) name a watchlist ingredient [{detail}]",
            )
            if declared == "UNKNOWN_DRUG_TYPE":
                report.info(
                    table,
                    "drug_type: the list is not prescription-only, so UNKNOWN_DRUG_TYPE is the "
                    "only DrugType true of every row",
                )
            else:
                report.warning(
                    table,
                    f"drug_type: config declares {declared}, which is false for the "
                    "over-the-counter rows above",
                )
        else:
            report.info(
                table,
                "over-the-counter watchlist: no match; a prescription-only list is possible -- "
                "confirm with AI-READI before changing drug_type",
            )
