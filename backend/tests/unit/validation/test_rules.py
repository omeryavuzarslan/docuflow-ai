"""Rule tests on the hand-checked factory documents.

Factory invoice (20% VAT): 3 x 19.99 = 59.97 (VAT 11.99); 2 x 5.125 = 10.25 (VAT 2.05);
totals 70.22 / 14.04 / 84.26. PO and DN match it exactly.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from backend.app.domain.calculations import invoice_totals, line_net, line_vat
from backend.app.domain.documents import DeliveryNote, Invoice
from backend.app.validation.models import Discrepancy, IncompleteDocument
from backend.app.validation.rules import validate
from backend.tests.unit.domain.factories import (
    make_delivery_note,
    make_invoice,
    make_purchase_order,
)
from data_generator.inject import evolve

D = Decimal


def _run(*docs: Any) -> list[Discrepancy]:
    return validate(list(docs)).discrepancies


def _set_line(invoice: Invoice, i: int, recompute: bool = False, **changes: Any) -> Invoice:
    line = evolve(invoice.lines[i], **changes)
    if recompute:
        net = line_net(line.quantity, line.unit_price)
        line = evolve(line, line_net=net, line_vat=line_vat(net, line.vat_rate))
    lines = (*invoice.lines[:i], line, *invoice.lines[i + 1 :])
    if not recompute:
        return evolve(invoice, lines=lines)
    t = invoice_totals(lines)
    return evolve(invoice, lines=lines, net_total=t.net, vat_total=t.vat, gross_total=t.gross)


def _dn(*quantities: str, document_id: str = "set001-dn", dn_number: str = "DN-1") -> DeliveryNote:
    dn = make_delivery_note()
    lines = tuple(
        evolve(line, quantity_delivered=D(q)) for line, q in zip(dn.lines, quantities, strict=True)
    )
    return evolve(dn, lines=lines, document_id=document_id, dn_number=dn_number)


def _summary(found: list[Discrepancy]) -> list[tuple[str, str, str | None]]:
    return [(d.rule, d.document_id, d.field) for d in found]


# --- clean ---------------------------------------------------------------------------


def test_matching_documents_produce_no_discrepancies() -> None:
    assert _run(make_purchase_order(), make_delivery_note(), make_invoice()) == []


# --- R1 quantity ---------------------------------------------------------------------


def test_r1_invoicing_more_than_delivered() -> None:
    invoice = _set_line(make_invoice(), 0, recompute=True, quantity=D("4"))
    [found] = _run(make_purchase_order(), make_delivery_note(), invoice)
    assert (found.rule, found.type, found.field) == ("R1", "quantity_mismatch", "lines[0].quantity")
    assert (found.expected, found.actual) == ("3.0000", "4.0000")
    assert found.amount_impact == D("19.99")  # one unit too many, net


def test_r1_partial_delivery_invoiced_as_delivered_is_not_an_error() -> None:
    invoice = _set_line(make_invoice(), 0, recompute=True, quantity=D("2"))
    assert _run(make_purchase_order(), _dn("2", "2"), invoice) == []


def test_r1_deliveries_are_summed_across_delivery_notes() -> None:
    first = _dn("1", "2")
    second = _dn("2", "0.0001", document_id="set001-dn-2", dn_number="DN-2")
    assert _run(make_purchase_order(), first, second, make_invoice()) == []


def test_r1_quantities_already_invoiced_are_used_up() -> None:
    # Two different invoices for the same delivery: together they bill everything twice.
    second = evolve(make_invoice("set001-inv-2"), invoice_number="INV-2026-0002")
    found = _run(make_purchase_order(), make_delivery_note(), make_invoice(), second)
    assert {(d.rule, d.document_id) for d in found} == {("R1", "set001-inv-2")}
    assert len(found) == 2  # both lines of the second invoice


# --- R2 price ------------------------------------------------------------------------


def test_r2_price_differs_from_the_order() -> None:
    invoice = _set_line(make_invoice(), 1, recompute=True, unit_price=D("5.50"))
    [found] = _run(make_purchase_order(), make_delivery_note(), invoice)
    assert (found.rule, found.type, found.field) == (
        "R2",
        "unit_price_mismatch",
        "lines[1].unit_price",
    )
    assert found.amount_impact == D("0.75")  # 2 x (5.50 - 5.125)


# --- R3 line total -------------------------------------------------------------------


def test_r3_wrong_line_total_is_reported_once_not_again_as_a_total() -> None:
    invoice = _set_line(make_invoice(), 0, line_net=D("60.97"))
    found = _run(make_purchase_order(), make_delivery_note(), invoice)
    assert _summary(found) == [("R3", "set001-inv-1", "lines[0].line_net")]
    assert found[0].expected == "59.97"


@pytest.mark.parametrize(("printed", "ok"), [("1.00", True), ("0.99", True), ("0.98", False)])
def test_r3_accepts_rounding_either_way_within_a_penny(printed: str, ok: bool) -> None:
    # 3 x 0.3333 = 0.9999: 1.00 (nearest) and 0.99 (truncated) are both honest roundings.
    po = make_purchase_order()
    po_lines = (evolve(po.lines[0], unit_price=D("0.3333"), line_net=D("1.00")), po.lines[1])
    po = evolve(po, lines=po_lines, net_total=D("11.25"))
    invoice = _set_line(make_invoice(), 0, recompute=True, unit_price=D("0.3333"))
    invoice = _set_line(invoice, 0, line_net=D(printed))
    t = invoice_totals(invoice.lines)
    invoice = evolve(invoice, net_total=t.net, vat_total=t.vat, gross_total=t.gross)
    rules = {d.rule for d in _run(po, make_delivery_note(), invoice)}
    assert ("R3" not in rules) is ok


# --- R4 / R5 VAT ---------------------------------------------------------------------


def _invoice_with_net(net: str, vat: str) -> Invoice:
    """One-line invoice whose numbers we control: 1 x net, VAT as given."""
    invoice = make_invoice()
    line = evolve(
        invoice.lines[0], quantity=D("1"), unit_price=D(net), line_net=D(net), line_vat=D(vat)
    )
    return evolve(
        invoice,
        lines=(line,),
        net_total=D(net),
        vat_total=D(vat),
        gross_total=D(net) + D(vat),
    )


def _po_for(invoice: Invoice) -> list[Any]:
    po = make_purchase_order()
    line = evolve(
        po.lines[0],
        quantity=D("1"),
        unit_price=invoice.lines[0].unit_price,
        line_net=invoice.net_total,
    )
    dn = make_delivery_note()
    return [
        evolve(po, lines=(line,), net_total=invoice.net_total),
        evolve(dn, lines=(evolve(dn.lines[0], quantity_delivered=D("1")),)),
    ]


@pytest.mark.parametrize(
    ("vat", "ok"), [("2.06", True), ("2.05", True), ("2.07", False), ("2.04", False)]
)
def test_r4_line_vat_rounded_to_nearest_or_down_is_accepted(vat: str, ok: bool) -> None:
    # 10.28 x 20% = 2.056: HMRC (VAT Notice 700, 17.5.1) allows 2.06 (nearest) or 2.05 (down).
    invoice = _invoice_with_net("10.28", vat)
    rules = {d.rule for d in _run(*_po_for(invoice), invoice)}
    assert ("R4" not in rules) is ok


def test_r4_wrong_line_vat_is_reported_once_not_again_as_vat_total() -> None:
    invoice = _set_line(make_invoice(), 1, line_vat=D("3.05"))
    found = _run(make_purchase_order(), make_delivery_note(), invoice)
    assert _summary(found) == [("R4", "set001-inv-1", "lines[1].line_vat")]


def test_r5_invoice_level_vat_is_accepted() -> None:
    # Per line: 11.99 + 2.05 = 14.04. Invoice level: 70.22 x 20% = 14.044 -> 14.04 too, so
    # use a total that only the invoice-level method gives: lines 0.01 + 0.01 vs 0.03 x 20%.
    invoice = make_invoice()
    a = evolve(
        invoice.lines[0],
        quantity=D("1"),
        unit_price=D("0.025"),
        line_net=D("0.03"),
        line_vat=D("0.01"),
    )
    b = evolve(
        invoice.lines[1],
        quantity=D("1"),
        unit_price=D("0.025"),
        line_net=D("0.03"),
        line_vat=D("0.01"),
    )
    for vat_total in ("0.02", "0.01"):  # sum of lines, and 0.06 x 20% = 0.012 -> 0.01
        inv = evolve(
            invoice,
            lines=(a, b),
            net_total=D("0.06"),
            vat_total=D(vat_total),
            gross_total=D("0.06") + D(vat_total),
        )
        assert "R5" not in {d.rule for d in validate([inv]).discrepancies}


def test_r5_wrong_vat_total() -> None:
    invoice = make_invoice()
    invoice = evolve(invoice, vat_total=D("15.04"), gross_total=D("85.26"))
    found = _run(make_purchase_order(), make_delivery_note(), invoice)
    assert _summary(found) == [("R5", "set001-inv-1", "vat_total")]


# --- R6 / R7 totals ------------------------------------------------------------------


def test_r6_wrong_net_total() -> None:
    invoice = evolve(make_invoice(), net_total=D("71.22"), gross_total=D("85.26"))
    found = _run(make_purchase_order(), make_delivery_note(), invoice)
    assert _summary(found) == [("R6", "set001-inv-1", "net_total")]


def test_r7_gross_is_not_net_plus_vat() -> None:
    invoice = evolve(make_invoice(), gross_total=D("94.26"))
    [found] = _run(make_purchase_order(), make_delivery_note(), invoice)
    assert (found.rule, found.type, found.field) == ("R7", "total_error", "gross_total")
    assert (found.expected, found.actual, found.amount_impact) == ("84.26", "94.26", D("10.00"))


# --- R8 duplicates -------------------------------------------------------------------


def test_r8_same_supplier_and_number_is_a_duplicate() -> None:
    duplicate = make_invoice("set001-inv-2")
    found = _run(make_purchase_order(), make_delivery_note(), make_invoice(), duplicate)
    assert [(d.rule, d.type, d.document_id, d.related_document_id) for d in found] == [
        ("R8", "duplicate_invoice", "set001-inv-2", "set001-inv-1")
    ]  # and the duplicate is not also reported as invoicing undelivered goods


def test_r8_the_earlier_invoice_is_the_original() -> None:
    later = evolve(make_invoice("a-first-by-id"), issue_date=date(2026, 10, 20))
    found = _run(make_purchase_order(), make_delivery_note(), later, make_invoice())
    assert [(d.document_id, d.related_document_id) for d in found] == [
        ("a-first-by-id", "set001-inv-1")
    ]


def test_r8_same_number_from_another_supplier_is_not_a_duplicate() -> None:
    other = make_invoice("other-inv")
    other = evolve(
        other, supplier=evolve(other.supplier, vat_number="GB000000001"), po_number="PO-X"
    )
    found = _run(make_purchase_order(), make_delivery_note(), make_invoice(), other)
    assert "R8" not in {d.rule for d in found}


# --- matching ------------------------------------------------------------------------


def test_invoice_without_a_matching_order_is_reported_unmatched() -> None:
    orphan = evolve(make_invoice(), po_number="PO-DOES-NOT-EXIST")
    found = _run(make_purchase_order(), make_delivery_note(), orphan)
    assert [(d.rule, d.type, d.document_id) for d in found] == [
        ("M1", "unmatched_document", "set001-inv-1")
    ]


def test_order_reference_must_belong_to_the_same_supplier() -> None:
    # Same PO number, different supplier: not the same order.
    invoice = make_invoice()
    invoice = evolve(invoice, supplier=evolve(invoice.supplier, vat_number="GB000000001"))
    found = _run(make_purchase_order(), make_delivery_note(), invoice)
    assert [d.type for d in found] == ["unmatched_document"]


def test_order_with_nothing_attached_is_fine() -> None:
    assert _run(make_purchase_order()) == []


# --- documents under review ----------------------------------------------------------


def test_invoice_is_held_not_flagged_when_its_order_is_under_review() -> None:
    pending = IncompleteDocument(
        document_id="set001-po", doc_type="purchase_order", po_number="PO-2026-0001"
    )
    report = validate([make_delivery_note(), make_invoice()], incomplete=[pending])
    assert report.discrepancies == []
    assert len(report.held) == 2  # the delivery note and the invoice


def test_quantity_check_is_held_when_a_delivery_note_is_under_review() -> None:
    pending = IncompleteDocument(
        document_id="set001-dn", doc_type="delivery_note", po_number="PO-2026-0001"
    )
    report = validate([make_purchase_order(), make_invoice()], incomplete=[pending])
    assert report.discrepancies == []  # without it, R1 would see nothing delivered
    assert report.held == ["PO-2026-0001: quantity check held, a delivery note is under review"]


def test_other_checks_still_run_while_a_delivery_note_is_under_review() -> None:
    pending = IncompleteDocument(
        document_id="set001-dn", doc_type="delivery_note", po_number="PO-2026-0001"
    )
    invoice = evolve(make_invoice(), gross_total=D("94.26"))
    found = validate([make_purchase_order(), invoice], incomplete=[pending]).discrepancies
    assert [d.rule for d in found] == ["R7"]


def test_sku_punctuation_noise_still_matches_the_line() -> None:
    dn = make_delivery_note()
    noisy = evolve(
        dn, lines=(evolve(dn.lines[0], sku="SKU.-001"), evolve(dn.lines[1], sku="sku 002"))
    )
    assert _run(make_purchase_order(), noisy, make_invoice()) == []


def test_r8_ties_on_date_are_broken_by_arrival_not_by_id() -> None:
    # Same date: the one received first is the original, whatever its id.
    first, second = make_invoice("zzz-received-first"), make_invoice("aaa-received-second")
    order = {"zzz-received-first": 1, "aaa-received-second": 2}
    found = validate(
        [make_purchase_order(), make_delivery_note(), first, second], received_order=order
    )
    assert [(d.rule, d.document_id) for d in found.discrepancies] == [("R8", "aaa-received-second")]
