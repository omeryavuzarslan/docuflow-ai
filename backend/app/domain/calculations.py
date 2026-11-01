"""The single place where document arithmetic lives.

Used by the data generator to build correct documents, and later by the rule engine to
work out what a document *should* say. Rounding happens only at these points: line net,
line VAT, and nothing else (totals are sums of already-rounded values). See ADR-0001.
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from backend.app.domain.documents import InvoiceLine

PENNY = Decimal("0.01")


class Totals(NamedTuple):
    net: Decimal
    vat: Decimal
    gross: Decimal


def round_money(value: Decimal) -> Decimal:
    """Round to whole pence, halves away from zero (0.125 -> 0.13).

    Python's default is banker's rounding (0.125 -> 0.12), which is not what invoices use.
    """
    return value.quantize(PENNY, rounding=ROUND_HALF_UP)


def line_net(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return round_money(quantity * unit_price)


def line_vat(net: Decimal, vat_rate: Decimal) -> Decimal:
    return round_money(net * vat_rate)


def invoice_totals(lines: Iterable[InvoiceLine]) -> Totals:
    """Sum the line values as they are written on the document.

    No rounding here: each line was already rounded, and sums of pence are exact.
    """
    lines = tuple(lines)
    net = sum((line.line_net for line in lines), Decimal("0.00"))
    vat = sum((line.line_vat for line in lines), Decimal("0.00"))
    return Totals(net=net, vat=vat, gross=net + vat)
