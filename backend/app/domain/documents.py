"""The three document types: purchase order (PO), delivery note (DN) and invoice.

Totals are stored fields, not computed properties. A real invoice can state a wrong total,
and the system must be able to represent that in order to detect it. The correct values
are computed separately in `calculations.py`.

`document_id` is our internal, unique id. The `*_number` fields are what is printed on the
document; two documents can share one (a duplicate invoice).

Collections are tuples rather than lists so that frozen models are immutable all the way
down.
"""

from datetime import date
from typing import Literal

from pydantic import Field

from backend.app.domain.parties import Buyer, Supplier
from backend.app.domain.types import DomainModel, Money, Quantity, UnitPrice, VatRate


class POLine(DomainModel):
    line_no: int = Field(ge=1)
    sku: str
    description: str
    quantity: Quantity
    unit_price: UnitPrice
    vat_rate: VatRate
    line_net: Money


class DNLine(DomainModel):
    """A delivery note says what arrived, not what it costs, so it has no prices."""

    line_no: int = Field(ge=1)
    sku: str
    description: str
    quantity_delivered: Quantity


class InvoiceLine(DomainModel):
    line_no: int = Field(ge=1)
    sku: str
    description: str
    quantity: Quantity
    unit_price: UnitPrice
    vat_rate: VatRate
    line_net: Money
    line_vat: Money


class PurchaseOrder(DomainModel):
    doc_type: Literal["purchase_order"] = "purchase_order"
    document_id: str
    po_number: str
    issue_date: date
    buyer: Buyer
    supplier: Supplier
    currency: Literal["GBP"] = "GBP"
    lines: tuple[POLine, ...] = Field(min_length=1)
    net_total: Money


class DeliveryNote(DomainModel):
    doc_type: Literal["delivery_note"] = "delivery_note"
    document_id: str
    dn_number: str
    po_number: str
    delivery_date: date
    buyer: Buyer
    supplier: Supplier
    lines: tuple[DNLine, ...] = Field(min_length=1)


class Invoice(DomainModel):
    doc_type: Literal["invoice"] = "invoice"
    document_id: str
    invoice_number: str
    po_number: str
    delivery_note_numbers: tuple[str, ...] = ()
    issue_date: date
    due_date: date
    buyer: Buyer
    supplier: Supplier
    currency: Literal["GBP"] = "GBP"
    lines: tuple[InvoiceLine, ...] = Field(min_length=1)
    net_total: Money
    vat_total: Money
    gross_total: Money
