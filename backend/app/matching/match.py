"""Three-way matching, step one: group each purchase order with its delivery notes and
invoices.

Documents belong together when they name the same PO number *and* come from the same
supplier (VAT number). The supplier check matters: PO numbers are only unique per buyer,
and an invoice quoting our PO number from a different company is not for that order.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder

Document = PurchaseOrder | DeliveryNote | Invoice


@dataclass(frozen=True)
class MatchGroup:
    purchase_order: PurchaseOrder
    delivery_notes: tuple[DeliveryNote, ...] = ()
    invoices: tuple[Invoice, ...] = ()

    def delivered_by_sku(self) -> dict[str, Decimal]:
        """Total delivered per SKU key (see `sku_key`) across every delivery note."""
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for note in self.delivery_notes:
            for line in note.lines:
                totals[sku_key(line.sku)] += line.quantity_delivered
        return dict(totals)


@dataclass(frozen=True)
class MatchResult:
    groups: tuple[MatchGroup, ...]
    unmatched: tuple[DeliveryNote | Invoice, ...] = field(default=())


def sku_key(sku: str) -> str:
    """SKUs compared on letters and digits only: OCR punctuation noise such as "CL.-2005"
    for "CL-2005" must not break a line match."""
    return "".join(ch for ch in sku.upper() if ch.isalnum())


def order_key(po_number: str, supplier_vat: str) -> tuple[str, str]:
    """Whitespace and case differences in references are not meaningful."""
    return ("".join(po_number.split()).upper(), "".join(supplier_vat.split()).upper())


def match_documents(documents: Iterable[Document]) -> MatchResult:
    docs = list(documents)
    orders: dict[tuple[str, str], PurchaseOrder] = {}
    for doc in docs:
        if isinstance(doc, PurchaseOrder):
            orders.setdefault(order_key(doc.po_number, doc.supplier.vat_number), doc)

    notes: dict[tuple[str, str], list[DeliveryNote]] = defaultdict(list)
    invoices: dict[tuple[str, str], list[Invoice]] = defaultdict(list)
    unmatched: list[DeliveryNote | Invoice] = []
    for doc in docs:
        if isinstance(doc, PurchaseOrder):
            continue
        key = order_key(doc.po_number, doc.supplier.vat_number)
        if key not in orders:
            unmatched.append(doc)
        elif isinstance(doc, DeliveryNote):
            notes[key].append(doc)
        else:
            invoices[key].append(doc)

    groups = tuple(
        MatchGroup(
            purchase_order=po,
            delivery_notes=tuple(notes[key]),
            invoices=tuple(sorted(invoices[key], key=_invoice_order)),
        )
        for key, po in orders.items()
    )
    return MatchResult(groups=groups, unmatched=tuple(unmatched))


def _invoice_order(invoice: Invoice) -> tuple[object, str]:
    # Earliest first, so "already invoiced" and "duplicate of" mean the same thing every run.
    return (invoice.issue_date, invoice.document_id)
