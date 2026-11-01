import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from backend.app.domain.document_set import DocumentSet
from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder
from backend.app.domain.errors import ErrorType
from data_generator.build import build_clean_set
from data_generator.inject import inject_error
from data_generator.plan import TEMPLATES, SetPlan
from data_generator.render import (
    format_date,
    format_money,
    format_price,
    format_quantity,
    format_vat_rate,
    render_html,
    render_pdf,
    write_pdfs,
)
from data_generator.rng import make_rng

D = Decimal


def _set(index: int = 1, error_type: ErrorType | None = None) -> DocumentSet:
    plan = SetPlan(index=index, template="classic", error_type=error_type, partial_delivery=False)
    doc_set = build_clean_set(42, plan)
    if error_type is not None:
        doc_set = inject_error(doc_set, error_type, make_rng(42, index, "inject"))
    return doc_set


def _pdf_text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


# --- formatting ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (D("0.00"), "£0.00"),
        (D("5.10"), "£5.10"),
        (D("1234.56"), "£1,234.56"),
        (D("1000000"), "£1,000,000.00"),
    ],
)
def test_format_money(value: Decimal, expected: str) -> None:
    assert format_money(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (D("19.9900"), "£19.99"),
        (D("0.0450"), "£0.045"),
        (D("0.0325"), "£0.0325"),
        (D("1250.5000"), "£1,250.50"),
    ],
)
def test_format_price_keeps_sub_penny_digits(value: Decimal, expected: str) -> None:
    assert format_price(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(D("3.0000"), "3"), (D("2.5000"), "2.5"), (D("2400.0000"), "2,400"), (D("0.2500"), "0.25")],
)
def test_format_quantity(value: Decimal, expected: str) -> None:
    assert format_quantity(value) == expected


def test_format_vat_rate_and_date() -> None:
    assert format_vat_rate(D("0.2000")) == "20%"
    assert format_vat_rate(D("0.0500")) == "5%"
    assert format_date(date(2026, 3, 6)) == "06/03/2026"  # UK: DD/MM/YYYY


# --- content -------------------------------------------------------------------------


@pytest.mark.parametrize("template", TEMPLATES)
def test_invoice_pdf_shows_its_data(template: str) -> None:
    invoice = _set().invoices[0]
    text = _pdf_text(render_pdf(invoice, template))
    for expected in (
        invoice.invoice_number,
        invoice.po_number,
        invoice.supplier.name,
        invoice.supplier.vat_number,
        invoice.buyer.name,
        format_date(invoice.issue_date),
        format_date(invoice.due_date),
        format_money(invoice.net_total),
        format_money(invoice.vat_total),
        format_money(invoice.gross_total),
        *(line.sku for line in invoice.lines),
        *(format_money(line.line_net) for line in invoice.lines),
    ):
        assert expected in text, expected


@pytest.mark.parametrize("template", TEMPLATES)
def test_purchase_order_pdf_shows_its_data(template: str) -> None:
    po = _set().purchase_order
    text = _pdf_text(render_pdf(po, template))
    for expected in (po.po_number, po.buyer.name, po.supplier.name, format_money(po.net_total)):
        assert expected in text, expected
    for line in po.lines:
        assert line.sku in text
        assert format_price(line.unit_price) in text


@pytest.mark.parametrize("template", TEMPLATES)
def test_delivery_note_pdf_has_quantities_but_no_prices(template: str) -> None:
    dn = _set().delivery_note
    text = _pdf_text(render_pdf(dn, template))
    assert dn.dn_number in text
    assert dn.po_number in text
    for line in dn.lines:
        assert line.sku in text
        assert format_quantity(line.quantity_delivered) in text
    assert "£" not in text


def test_pdf_shows_the_injected_wrong_value_not_the_correct_one() -> None:
    doc_set = _set(index=7, error_type=ErrorType.TOTAL_ERROR)
    error = doc_set.errors[0]
    assert error.actual is not None and error.expected is not None
    text = _pdf_text(render_pdf(doc_set.invoices[0], "classic"))
    assert format_money(D(error.actual)) in text
    assert format_money(D(error.expected)) not in text


def test_special_characters_are_escaped_not_broken() -> None:
    # "Harbour & Hale" must come out as "&", not "&amp;" or a broken tag.
    sets = (_set(index=i) for i in range(1, 30))
    invoice = next(s.invoices[0] for s in sets if "&" in s.invoices[0].buyer.name)
    assert "&amp;amp;" not in render_html(invoice, "modern")
    assert invoice.buyer.name in _pdf_text(render_pdf(invoice, "modern"))


# --- templates and determinism -------------------------------------------------------


def test_templates_look_different_but_carry_the_same_data() -> None:
    invoice = _set().invoices[0]
    classic, modern = render_html(invoice, "classic"), render_html(invoice, "modern")
    assert classic != modern
    for html in (classic, modern):
        assert invoice.invoice_number in html


def test_same_document_renders_to_identical_bytes() -> None:
    invoice = _set().invoices[0]
    assert render_pdf(invoice, "modern") == render_pdf(invoice, "modern")


def test_unknown_template_is_an_error() -> None:
    with pytest.raises(ValueError, match="template"):
        render_html(_set().invoices[0], "fancy")


# --- files ---------------------------------------------------------------------------


def test_write_pdfs_names_files_after_the_document(tmp_path: Path) -> None:
    doc_set = _set(index=8, error_type=ErrorType.DUPLICATE_INVOICE)
    files = write_pdfs(doc_set, tmp_path)
    assert files == {
        "set-008-po": "po.pdf",
        "set-008-dn": "dn.pdf",
        "set-008-inv-1": "inv-1.pdf",
        "set-008-inv-2": "inv-2.pdf",
    }
    for name in files.values():
        assert (tmp_path / name).read_bytes().startswith(b"%PDF")


def test_documents_render_for_every_type() -> None:
    doc_set = _set()
    docs: list[PurchaseOrder | DeliveryNote | Invoice] = [
        doc_set.purchase_order,
        doc_set.delivery_note,
        *doc_set.invoices,
    ]
    for doc in docs:
        assert render_pdf(doc, "classic").startswith(b"%PDF")
