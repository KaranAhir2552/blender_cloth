import pytest

from ai_garment.core.errors import GarmentError
from ai_garment.core.units import parse_amount


@pytest.mark.parametrize("text,kind,value", [
    ("+10%", "percent", 10.0),
    ("-5%", "percent", -5.0),
    ("10 %", "percent", 10.0),
    ("+3cm", "length", 0.03),
    ("-2 cm", "length", -0.02),
    ("15mm", "length", 0.015),
    ("2in", "length", 0.0508),
    ("0.05", "length", 0.05),
    (0.1, "length", 0.1),
])
def test_parse_amount(text, kind, value):
    a = parse_amount(text)
    assert a.kind == kind
    assert a.value == pytest.approx(value)


def test_apply():
    assert parse_amount("+10%").apply(1.0) == pytest.approx(1.1)
    assert parse_amount("-5%").apply(2.0) == pytest.approx(1.9)
    assert parse_amount("+3cm").apply(1.0) == pytest.approx(1.03)


def test_to_string_round_trip():
    for s in ("+10%", "-5%", "+3cm", "-2cm"):
        assert parse_amount(parse_amount(s).to_string()).value == pytest.approx(parse_amount(s).value)


@pytest.mark.parametrize("bad", ["abc", "", "10 parsecs", None, "%"])
def test_invalid_amount(bad):
    with pytest.raises(GarmentError) as exc:
        parse_amount(bad)
    assert exc.value.code == "INVALID_AMOUNT"
