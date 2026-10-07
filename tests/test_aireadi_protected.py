"""The AI-READI protected supplement: REDCap exports -> sex, gender, race/ethnicity, medications.

Fixture: ``tests/data/aireadi/protected/`` (see that directory's README). Every rule the reader
and the preflight enforce is pinned here. The free-text canaries are the privacy lock: every
free-text cell in the fixture starts with ``CANARY-`` and none may reach a packet, the IR or
the report.
"""

import csv
import shutil
from datetime import datetime
from pathlib import Path

import phenopackets as pp
import pytest
from google.protobuf.json_format import MessageToJson, Parse
from pydantic import ValidationError

from b2ai_dataset_ingest.emitters import PhenopacketEmitter
from b2ai_dataset_ingest.mapping.loaders import load_mapping, validate_mapping
from b2ai_dataset_ingest.model import OntologyTerm, TreatmentObservation
from b2ai_dataset_ingest.sources.aireadi import AireadiSource
from b2ai_dataset_ingest.sources.aireadi.validate import validate_aireadi

CONFIG_DIR = Path(__file__).parents[1] / "config" / "aireadi"
FIXTURE = Path(__file__).parent / "data" / "aireadi"
PROTECTED = FIXTURE / "protected"

CANARY = "CANARY-"


@pytest.fixture(scope="module")
def run():
    source = AireadiSource(FIXTURE, CONFIG_DIR, protected_dir=PROTECTED)
    participants = {p.individual.id: p for p in source.read()}
    return source.report, participants


@pytest.fixture(scope="module")
def participants(run):
    return run[1]


@pytest.fixture(scope="module")
def report(run):
    return run[0]


@pytest.fixture(scope="module")
def packets(participants):
    emitter = PhenopacketEmitter()
    return {pid: emitter.emit(p) for pid, p in participants.items()}


# ---------- the supplement enriches; it never creates
def test_unmatched_supplement_ids_do_not_create_participants(participants, report):
    """900099 is in both exports and in no clinical table: counted, never emitted."""
    assert set(participants) == {"900001", "900002", "900003", "900004"}
    assert report.protected_rows_unmatched["protected_demographics"] == 1
    assert report.protected_rows_unmatched["protected_medications"] == 1


def test_without_protected_dir_nothing_changes():
    """The supplement is opt-in; the plain OMOP run is byte-for-byte what it was."""
    plain = {p.individual.id: p for p in AireadiSource(FIXTURE, CONFIG_DIR).read()}
    assert all(p.individual.sex is None for p in plain.values())
    assert all(p.individual.gender is None for p in plain.values())
    assert all(not p.individual.race and not p.individual.ethnicity for p in plain.values())
    assert all(p.treatments == [] for p in plain.values())


# ---------- demographics -> Individual
def test_supplement_sets_sex_over_the_redacted_person_table(participants, report):
    """person.csv carries gender_concept_id = 0 on every row; scrsex wins."""
    assert participants["900001"].individual.sex == "FEMALE"
    assert participants["900002"].individual.sex == "MALE"
    # Intersex recodes to OTHER_SEX: "not possible to assess the applicability of MALE/FEMALE".
    assert participants["900003"].individual.sex == "OTHER_SEX"
    # 777 "prefer not to say" leaves the field unset, and is counted as a refusal.
    assert participants["900004"].individual.sex is None
    assert report.protected_fields_set["sex"] == 3
    assert report.sentinel_answers["protected_demographics.scrsex"] == 1


def test_gender_identity_is_an_ncit_term(participants, report):
    assert participants["900001"].individual.gender.id == "NCIT:C205466"  # woman
    assert participants["900002"].individual.gender.id == "NCIT:C205467"  # man
    assert participants["900003"].individual.gender.id == "NCIT:C160941"  # non-binary
    assert participants["900004"].individual.gender is None  # 777
    assert report.sentinel_answers["protected_demographics.genderid"] == 1


def test_race_and_ethnicity_land_in_the_ir_with_the_corrected_code(participants, report):
    """900002 ticks race___c17459. In NCIT, C17459 is *Hispanic or Latino*; the config maps the
    column to the concept the form meant, NCIT:C41259 American Indian or Alaska Native."""
    race = {t.id for t in participants["900002"].individual.race}
    assert race == {"NCIT:C41259", "NCIT:C41260"}
    assert "NCIT:C17459" not in race
    ethnicity = {t.id for t in participants["900002"].individual.ethnicity}
    assert ethnicity == {"NCIT:C67113", "NCIT:C209381"}  # Mexican + Chicano (source code C999)
    assert [t.id for t in participants["900001"].individual.race] == ["NCIT:C41261"]
    assert [t.id for t in participants["900001"].individual.ethnicity] == ["NCIT:C41222"]


def test_race_refusal_and_other_leave_no_term_and_are_counted_differently(participants, report):
    assert participants["900003"].individual.race == []
    assert report.sentinel_answers["protected_demographics.race___777"] == 1
    assert participants["900004"].individual.race == []
    assert report.items_dropped["protected_demographics.race___888"] == 1
    assert participants["900003"].individual.ethnicity == []
    assert report.items_dropped["protected_demographics.ethnic___888"] == 1
    assert report.protected_fields_set["race"] == 2
    assert report.protected_fields_set["ethnicity"] == 3


def test_race_and_ethnicity_never_reach_the_packet_but_gender_does(packets):
    """Schema v2 has no race/ethnicity slot (verified 2026-10-06), so the emitter writes none."""
    text = MessageToJson(packets["900002"])
    assert "NCIT:C41259" not in text and "NCIT:C67113" not in text
    assert "race" not in text.lower() and "ethnicity" not in text.lower()
    assert packets["900002"].subject.gender.id == "NCIT:C205467"
    assert packets["900002"].subject.sex == pp.MALE


# ---------- medications -> TreatmentObservation -> MedicalAction
def _treatments(participants, pid):
    return participants[pid].treatments


def test_a_medication_becomes_a_treatment_with_agent_route_dose_and_frequency(participants):
    levo = next(t for t in _treatments(participants, "900001") if t.agent.id == "rxnorm:10582")
    assert levo.agent.label == "levothyroxine"  # the in-file term, never resolved externally
    assert levo.route.id == "NCIT:C38288"  # oral
    assert (levo.dose.value, levo.dose.unit.id) == (125.0, "UCUM:ug")
    assert levo.frequency.id == "NCIT:C125004"  # once daily
    assert levo.drug_type == "UNKNOWN_DRUG_TYPE"
    assert levo.time.age_iso8601 == "P52Y"  # the participants.tsv anchor


def test_dose_and_frequency_stay_in_the_ir_and_are_counted_as_withheld(packets, report):
    actions = packets["900001"].medical_actions
    assert len(actions) == 2
    for action in actions:
        assert action.treatment.agent.id.startswith("rxnorm:")
        assert not action.treatment.dose_intervals
    # Five treatments carry a dose and/or a frequency the emitter did not write.
    assert report.treatments_emitted == 5
    assert report.doses_withheld == 5


def test_unknown_drug_type_is_the_proto_default_and_is_omitted_from_the_json(packets):
    text = MessageToJson(packets["900001"])
    assert '"medicalActions"' in text
    assert '"drugType"' not in text
    assert '"doseIntervals"' not in text


def test_rows_without_or_with_a_malformed_rxnorm_code_are_skipped_and_counted(
    participants, report
):
    assert report.agents_missing["protected_medications.rxnorm_code"] == 1
    assert report.agents_malformed["protected_medications.rxnorm_code"] == 1
    # 900004's only surviving row is the ONCE one.
    [only] = _treatments(participants, "900004")
    assert only.agent.id == "rxnorm:10582" and only.agent.label == "Levothyroxine Sodium"
    assert only.frequency is None  # ONCE has no NCIT schedule-frequency term
    assert (only.dose.value, only.dose.unit.id) == (5.0, "UCUM:mg")


def test_an_excel_date_mangled_dose_is_counted_not_parsed(participants, report):
    """Excel turned a free-text dose into a date. The medication survives without a dose."""
    [metformin] = _treatments(participants, "900002")
    assert metformin.agent.id == "rxnorm:6809"
    assert metformin.dose is None
    assert metformin.frequency.id == "NCIT:C64496"  # twice daily
    assert report.doses_unparsed["protected_medications.cmdos"] == 1


def test_other_route_and_other_unit_drop_the_slot_but_keep_the_agent(participants, report):
    [cream] = _treatments(participants, "900003")
    assert cream.route is None  # 888 Other: the free-text companion is never read
    assert cream.dose is None  # unit 18 Other
    assert cream.frequency.id == "NCIT:C64499"  # as needed
    assert report.items_dropped["protected_medications.cmroute"] == 1
    assert report.dose_units_unmapped["protected_medications.cmdosu"] == 1


def test_duplicate_instances_and_other_instruments_are_skipped(report):
    assert report.rows_skipped["protected_medications.duplicate instance"] == 1
    assert report.rows_skipped["protected_medications.other instrument"] == 1


def test_treatment_round_trips_with_an_rxnorm_resource_declared(packets, tmp_path):
    from b2ai_dataset_ingest.emitters.phenopacket import _collect_prefixes

    for pid, packet in packets.items():
        path = tmp_path / f"{pid}.json"
        path.write_text(MessageToJson(packet))
        parsed = Parse(path.read_text(), pp.Phenopacket())
        declared = {r.namespace_prefix.upper() for r in parsed.meta_data.resources}
        assert set(_collect_prefixes(parsed)) <= declared
    resources = {r.namespace_prefix: r for r in packets["900001"].meta_data.resources}
    assert resources["rxnorm"].iri_prefix.startswith("https://mor.nlm.nih.gov/RxNav/")


# ---------- the privacy lock
def test_free_text_columns_are_never_read(participants, packets, report):
    """Every free-text cell in the fixture is a CANARY-; none may surface anywhere."""
    for participant in participants.values():
        assert CANARY not in participant.model_dump_json()
    for packet in packets.values():
        assert CANARY not in MessageToJson(packet)
    rendered = report.render()
    assert CANARY not in rendered
    assert "9000" not in rendered  # no id either


# ---------- the .xlsx path
def _typed(cell: str):
    """Type a CSV cell the way Excel types the delivered export."""
    if cell == "":
        return None
    if cell.isdigit():
        return int(cell)
    try:
        return datetime.fromisoformat(cell)  # the date-mangled dose
    except ValueError:
        return cell


def _to_workbook(csv_path: Path, xlsx_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "in"
    with open(csv_path, newline="") as fh:
        for index, row in enumerate(csv.reader(fh)):
            sheet.append(row if index == 0 else [_typed(cell) for cell in row])
    workbook.save(xlsx_path)


def test_xlsx_and_csv_exports_read_identically(participants, report, tmp_path):
    """Excel types cells (int / str / datetime); the reader must see the same rows a CSV gives."""
    _to_workbook(
        PROTECTED / "Demographics_Protected_fixture.csv", tmp_path / "Demographics_Protected.xlsx"
    )
    _to_workbook(
        PROTECTED / "Medications_Protected_fixture.csv", tmp_path / "Medications_Protected.xlsx"
    )
    # An Excel lock file must be ignored, not read as a second match.
    (tmp_path / "~$Medications_Protected.xlsx").write_bytes(b"")
    source = AireadiSource(FIXTURE, CONFIG_DIR, protected_dir=tmp_path)
    via_xlsx = {p.individual.id: p for p in source.read()}
    assert {k: v.model_dump() for k, v in via_xlsx.items()} == {
        k: v.model_dump() for k, v in participants.items()
    }
    assert source.report.doses_unparsed == report.doses_unparsed
    assert source.report.protected_fields_set == report.protected_fields_set
    assert sorted(source.report.tables_read) == sorted(report.tables_read)


# ---------- the preflight
def test_validate_protected_reports_counts_only_and_settles_drug_type():
    result = validate_aireadi(FIXTURE, CONFIG_DIR, protected=PROTECTED)
    assert result.errors == [], result.render()
    text = result.render()
    assert "protected_demographics" in text and "protected_medications" in text
    assert "aspirin=<5" in text  # the watchlist hit, small-cell suppressed
    assert "UNKNOWN_DRUG_TYPE is the only DrugType true of every row" in text
    assert "more than one distinct term" in text  # 10582 as two spellings
    assert "typed as dates" in text  # the Excel-mangled dose
    assert "match no participant" in text  # 900099
    assert "free-text column(s) present and never read" in text
    assert CANARY not in text
    assert "9000" not in text


def test_validate_protected_errors_on_a_missing_mapped_column(tmp_path):
    target = tmp_path / "protected"
    shutil.copytree(PROTECTED, target)
    path = target / "Demographics_Protected_fixture.csv"
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh))
    drop = rows[0].index("race___c41261")
    with open(path, "w", newline="") as fh:
        csv.writer(fh).writerows([r[:drop] + r[drop + 1 :] for r in rows])
    result = validate_aireadi(FIXTURE, CONFIG_DIR, protected=target)
    assert any("race___c41261" in f.message for f in result.errors), result.render()


def test_validate_protected_errors_when_an_export_is_missing_or_ambiguous(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = validate_aireadi(FIXTURE, CONFIG_DIR, protected=empty)
    assert len([f for f in result.errors if "found 0" in f.message]) == 2

    twice = tmp_path / "twice"
    twice.mkdir()
    for name in ("Demographics_Protected_a.csv", "Demographics_Protected_b.csv"):
        shutil.copy(PROTECTED / "Demographics_Protected_fixture.csv", twice / name)
    result = validate_aireadi(FIXTURE, CONFIG_DIR, protected=twice)
    assert any("found 2" in f.message for f in result.errors), result.render()


def test_cli_accepts_protected_on_both_commands(tmp_path):
    from typer.testing import CliRunner

    from b2ai_dataset_ingest.cli import app

    runner = CliRunner()
    preflight = runner.invoke(
        app,
        ["validate-aireadi", "-i", str(FIXTURE), "-c", str(CONFIG_DIR), "-p", str(PROTECTED)],
    )
    assert preflight.exit_code == 0, preflight.output
    ingest = runner.invoke(
        app,
        [
            "aireadi",
            "-i",
            str(FIXTURE),
            "-c",
            str(CONFIG_DIR),
            "-o",
            str(tmp_path / "pp"),
            "-p",
            str(PROTECTED),
        ],
    )
    assert ingest.exit_code == 0, ingest.output
    assert "treatments:          5" in ingest.output
    assert '"medicalActions"' in (tmp_path / "pp" / "900001.json").read_text()


# ---------- configs
def test_protected_configs_carry_no_placeholder_terms():
    for path in sorted((CONFIG_DIR / "protected").glob("*.yaml")):
        assert validate_mapping(load_mapping(path)) == [], path.name


def test_the_shipped_config_corrects_the_dictionary_race_code():
    mapping = load_mapping(CONFIG_DIR / "protected" / "demographics.yaml")
    choices = mapping["checkbox_groups"]["race"]["choices"]
    assert choices["C17459"]["id"] == "NCIT:C41259"
    assert mapping["checkbox_groups"]["ethnic"]["choices"]["C999"]["id"] == "NCIT:C209381"
    assert mapping["drug_type"] if "drug_type" in mapping else True


def test_validate_mapping_walks_the_redcap_shapes():
    """A TODO anywhere in the supplement configs must warn, or it ships silently."""
    todo = {"id": "TODO", "label": "TODO"}
    medications = load_mapping(CONFIG_DIR / "protected" / "medications.yaml")
    medications["route"]["terms"]["6"] = todo
    medications["dose"]["units"]["8"] = todo
    medications["frequency"]["terms"]["QD"] = todo
    assert len(validate_mapping(medications)) == 3
    demographics = load_mapping(CONFIG_DIR / "protected" / "demographics.yaml")
    demographics["checkbox_groups"]["race"]["choices"]["C41260"] = todo
    demographics["columns"]["genderid"]["value_map"]["1"] = todo
    assert len(validate_mapping(demographics)) == 2


def test_drug_type_must_be_a_schema_enum_name():
    with pytest.raises(ValidationError):
        TreatmentObservation(agent=OntologyTerm(id="rxnorm:1"), drug_type="BOGUS")
    assert TreatmentObservation(agent=OntologyTerm(id="rxnorm:1")).drug_type == "UNKNOWN_DRUG_TYPE"
