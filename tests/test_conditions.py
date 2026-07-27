"""The ``when_value`` condition grammar: parsing and evaluation (ADR-0002)."""

import pytest

from b2ai_dataset_ingest.mapping.conditions import (
    Answer,
    ConditionParseError,
    parse_condition,
)


def _matches(expr: str, *, raw: str = "", ordinal: int | None = None) -> bool:
    return parse_condition(expr).matches(Answer(raw=raw, ordinal=ordinal))


# ------------------------------------------------------------------ numeric operators


@pytest.mark.parametrize(
    ("expr", "ordinal", "expected"),
    [
        (">=1", 0, False),
        (">=1", 1, True),
        (">=1", 3, True),
        ("==0", 0, True),
        ("==0", 1, False),
        ("!=0", 0, False),
        ("!=0", 2, True),
        (">0", 0, False),
        (">0", 1, True),
        ("<2", 1, True),
        ("<2", 2, False),
        ("<=3", 3, True),
        ("<=3", 4, False),
    ],
)
def test_numeric_comparisons(expr: str, ordinal: int, expected: bool):
    assert _matches(expr, ordinal=ordinal) is expected


def test_conjunction_requires_all_terms():
    assert _matches(">=1 & <=3", ordinal=2) is True
    assert _matches(">=1 & <=3", ordinal=0) is False
    assert _matches(">=1 & <=3", ordinal=4) is False


def test_membership_numeric():
    assert _matches("in {1,2,3}", ordinal=2) is True
    assert _matches("in {1,2,3}", ordinal=0) is False
    # a float-formatted numeric raw normalizes for membership
    assert _matches("in {1,2,3}", raw="2.0") is True


# ------------------------------------------------------------------- string operators


def test_string_equality_uses_raw_and_is_case_insensitive():
    assert _matches('== "Checked"', raw="Checked") is True
    assert _matches('== "Checked"', raw="checked") is True
    assert _matches('== "Checked"', raw="Unchecked") is False
    assert _matches('!= "Unchecked"', raw="Checked") is True


def test_string_membership_and_bare_token():
    assert _matches('in {"a","b"}', raw="A") is True
    assert _matches('in {"a","b"}', raw="c") is False
    # an unquoted operand is accepted as a string literal
    assert _matches("== Checked", raw="Checked") is True


# ------------------------------------------------------------------ answer resolution


def test_numeric_op_prefers_ordinal_then_numeric_raw():
    # A label answer with no resolved ordinal cannot satisfy a numeric gate.
    assert _matches(">=2", raw="Several days", ordinal=None) is False
    # ...but a numeric-entry cell with no ordinal falls back to its numeric value.
    assert _matches(">=2", raw="3.0", ordinal=None) is True
    # ordinal wins over a (possibly non-numeric) raw cell.
    assert _matches(">=2", raw="Nearly every day", ordinal=3) is True


# --------------------------------------------------------------------- parse failures


@pytest.mark.parametrize(
    "bad",
    ["", "   ", ">= foo", 'in {}', "in {1,,2}", "garbage", ">=1 &", "& <=3", ">="],
)
def test_malformed_expressions_raise(bad: str):
    with pytest.raises(ConditionParseError):
        parse_condition(bad)


def test_ordering_operator_rejects_string_operand():
    with pytest.raises(ConditionParseError):
        parse_condition('>= "Checked"')


def test_raw_expression_is_preserved():
    cond = parse_condition(" >=1 & <=3 ")
    assert cond.raw == ">=1 & <=3"
    assert len(cond.comparisons) == 2
