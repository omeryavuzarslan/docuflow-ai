from decimal import Decimal

import pytest

from backend.app.domain.calculations import invoice_totals, line_net, line_vat, round_money
from backend.tests.unit.domain.factories import make_invoice_lines

D = Decimal


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (D("0.125"), D("0.13")),  # banker's rounding would give 0.12
        (D("0.135"), D("0.14")),
        (D("0.124"), D("0.12")),
        (D("11.994"), D("11.99")),
        (D("2.5"), D("2.50")),
        (D("-0.125"), D("-0.13")),  # half away from zero
    ],
)
def test_round_money_is_half_up(value: Decimal, expected: Decimal) -> None:
    result = round_money(value)
    assert result == expected
    assert result.as_tuple().exponent == -2


def test_line_net_rounds_quantity_times_price() -> None:
    assert line_net(D("3"), D("19.99")) == D("59.97")
    assert line_net(D("2"), D("5.125")) == D("10.25")
    assert line_net(D("3"), D("0.3333")) == D("1.00")  # 0.9999


def test_line_vat_rounds_per_line() -> None:
    assert line_vat(D("59.97"), D("0.20")) == D("11.99")  # 11.994
    assert line_vat(D("0.05"), D("0.20")) == D("0.01")  # 0.010
    assert line_vat(D("0.025"), D("0.20")) == D("0.01")  # 0.005 -> half up


def test_invoice_totals_sums_the_lines_as_written() -> None:
    totals = invoice_totals(make_invoice_lines())
    assert totals.net == D("70.22")
    assert totals.vat == D("14.04")
    assert totals.gross == D("84.26")


def test_per_line_vat_can_differ_from_per_invoice_vat() -> None:
    # Documents why ADR-0001 matters: three lines of 0.025 net each.
    lines_vat = sum(line_vat(D("0.025"), D("0.20")) for _ in range(3))
    invoice_level_vat = round_money(D("0.075") * D("0.20"))
    assert lines_vat == D("0.03")
    assert invoice_level_vat == D("0.02")
