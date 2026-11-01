"""Small, hand-checked documents for domain tests.

Invoice lines (20% VAT, per-line rounding):
  1: 3 x 19.99  -> net 59.97, VAT 11.994 -> 11.99
  2: 2 x 5.125  -> net 10.25, VAT  2.05
  totals: net 70.22, VAT 14.04, gross 84.26
"""

from datetime import date
from decimal import Decimal

from backend.app.domain.document_set import DocumentSet
from backend.app.domain.documents import (
    DeliveryNote,
    DNLine,
    Invoice,
    InvoiceLine,
    POLine,
    PurchaseOrder,
)
from backend.app.domain.errors import ErrorType, InjectedError
from backend.app.domain.parties import Address, Buyer, Supplier

D = Decimal
VAT_20 = D("0.20")


def make_supplier() -> Supplier:
    return Supplier(
        name="Northwind Supplies Ltd",
        vat_number="GB123456789",
        address=Address(line1="1 Mill Lane", city="Leeds", postcode="LS1 4AB"),
    )


def make_buyer() -> Buyer:
    return Buyer(
        name="Acme Retail plc",
        vat_number="GB987654321",
        address=Address(line1="20 High Street", city="Oxford", postcode="OX1 1AA"),
    )


def make_invoice_lines() -> tuple[InvoiceLine, ...]:
    return (
        InvoiceLine(
            line_no=1,
            sku="SKU-001",
            description="A4 paper, 500 sheets",
            quantity=D("3"),
            unit_price=D("19.99"),
            vat_rate=VAT_20,
            line_net=D("59.97"),
            line_vat=D("11.99"),
        ),
        InvoiceLine(
            line_no=2,
            sku="SKU-002",
            description="Ballpoint pens, box of 10",
            quantity=D("2"),
            unit_price=D("5.125"),
            vat_rate=VAT_20,
            line_net=D("10.25"),
            line_vat=D("2.05"),
        ),
    )


def make_purchase_order() -> PurchaseOrder:
    return PurchaseOrder(
        document_id="set001-po",
        po_number="PO-2026-0001",
        issue_date=date(2026, 10, 1),
        buyer=make_buyer(),
        supplier=make_supplier(),
        lines=(
            POLine(
                line_no=1,
                sku="SKU-001",
                description="A4 paper, 500 sheets",
                quantity=D("3"),
                unit_price=D("19.99"),
                vat_rate=VAT_20,
                line_net=D("59.97"),
            ),
            POLine(
                line_no=2,
                sku="SKU-002",
                description="Ballpoint pens, box of 10",
                quantity=D("2"),
                unit_price=D("5.125"),
                vat_rate=VAT_20,
                line_net=D("10.25"),
            ),
        ),
        net_total=D("70.22"),
    )


def make_delivery_note() -> DeliveryNote:
    return DeliveryNote(
        document_id="set001-dn",
        dn_number="DN-2026-0001",
        po_number="PO-2026-0001",
        delivery_date=date(2026, 10, 5),
        buyer=make_buyer(),
        supplier=make_supplier(),
        lines=(
            DNLine(
                line_no=1,
                sku="SKU-001",
                description="A4 paper, 500 sheets",
                quantity_delivered=D("3"),
            ),
            DNLine(
                line_no=2,
                sku="SKU-002",
                description="Ballpoint pens, box of 10",
                quantity_delivered=D("2"),
            ),
        ),
    )


def make_invoice(document_id: str = "set001-inv-1") -> Invoice:
    return Invoice(
        document_id=document_id,
        invoice_number="INV-2026-0001",
        po_number="PO-2026-0001",
        delivery_note_numbers=("DN-2026-0001",),
        issue_date=date(2026, 10, 6),
        due_date=date(2026, 11, 5),
        buyer=make_buyer(),
        supplier=make_supplier(),
        lines=make_invoice_lines(),
        net_total=D("70.22"),
        vat_total=D("14.04"),
        gross_total=D("84.26"),
    )


def make_document_set(
    invoices: tuple[Invoice, ...] | None = None,
    errors: tuple[InjectedError, ...] = (),
) -> DocumentSet:
    return DocumentSet(
        set_id="set001",
        template="classic",
        purchase_order=make_purchase_order(),
        delivery_note=make_delivery_note(),
        invoices=invoices if invoices is not None else (make_invoice(),),
        errors=errors,
    )


def make_duplicate_error() -> InjectedError:
    return InjectedError(
        type=ErrorType.DUPLICATE_INVOICE,
        document_id="set001-inv-2",
        field=None,
        expected=None,
        actual=None,
        related_document_id="set001-inv-1",
    )
