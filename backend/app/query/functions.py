"""Fixed, parameterised queries for structured questions.

The LLM never writes SQL. The router (router.py) only picks one of these functions and fills
its parameters; the values are bound parameters, filtered by owner, and money is summed by
Postgres in NUMERIC and returned as Decimal.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    DeliveryNoteRow,
    DiscrepancyRow,
    DocumentRow,
    InvoiceRow,
    PurchaseOrderRow,
)


@dataclass(frozen=True)
class InvoiceTotals:
    count: int
    net: Decimal
    vat: Decimal
    gross: Decimal
    suppliers: list[str]  # which suppliers matched, so the answer can say so


@dataclass(frozen=True)
class FoundDocument:
    document_id: str
    doc_type: str
    number: str
    status: str
    filename: str


@dataclass(frozen=True)
class FindingSummary:
    discrepancy_id: str
    document_id: str
    filename: str
    rule: str
    type: str
    message: str
    amount_impact: Decimal | None
    status: str


def _contains(text: str) -> str:
    """A LIKE pattern matching `text` anywhere, with LIKE's own wildcards escaped."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def invoice_totals(
    session: Session,
    owner_id: str,
    supplier: str | None = None,
    buyer: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> InvoiceTotals:
    """Count and sum invoices by invoice date (inclusive range), optionally per party.
    Party names match case-insensitively on any part ("kestrel" matches "Kestrel ... Ltd")."""
    conditions = [InvoiceRow.owner_id == owner_id]
    if supplier:
        conditions.append(InvoiceRow.supplier_name.ilike(_contains(supplier), escape="\\"))
    if buyer:
        conditions.append(InvoiceRow.buyer_name.ilike(_contains(buyer), escape="\\"))
    if date_from:
        conditions.append(InvoiceRow.issue_date >= date_from)
    if date_to:
        conditions.append(InvoiceRow.issue_date <= date_to)
    count, net, vat, gross = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(InvoiceRow.net_total), 0),
            func.coalesce(func.sum(InvoiceRow.vat_total), 0),
            func.coalesce(func.sum(InvoiceRow.gross_total), 0),
        ).where(*conditions)
    ).one()
    suppliers = session.scalars(
        select(InvoiceRow.supplier_name)
        .where(*conditions)
        .distinct()
        .order_by(InvoiceRow.supplier_name)
    ).all()
    return InvoiceTotals(
        count=int(count),
        net=Decimal(net).quantize(Decimal("0.01")),
        vat=Decimal(vat).quantize(Decimal("0.01")),
        gross=Decimal(gross).quantize(Decimal("0.01")),
        suppliers=list(suppliers),
    )


def _norm_number(column: Any) -> Any:
    return func.upper(func.replace(func.replace(column, "-", ""), " ", ""))


def find_documents(session: Session, owner_id: str, number: str) -> list[FoundDocument]:
    """Documents whose own number is `number`; hyphens, spaces and case are ignored."""
    target = "".join(number.split()).replace("-", "").upper()
    found: list[FoundDocument] = []
    for row_class, column, doc_type in (
        (InvoiceRow, InvoiceRow.invoice_number, "invoice"),
        (PurchaseOrderRow, PurchaseOrderRow.po_number, "purchase_order"),
        (DeliveryNoteRow, DeliveryNoteRow.dn_number, "delivery_note"),
    ):
        rows = session.execute(
            select(row_class.document_id, column, DocumentRow.status, DocumentRow.filename)
            .join(DocumentRow, DocumentRow.id == row_class.document_id)
            .where(row_class.owner_id == owner_id, _norm_number(column) == target)
        )
        found += [FoundDocument(d, doc_type, n, s, f) for d, n, s, f in rows]
    return sorted(found, key=lambda d: (d.doc_type, d.document_id))


def list_findings(
    session: Session, owner_id: str, status: str = "open", supplier: str | None = None
) -> list[FindingSummary]:
    """Findings by status ("any" for all), optionally for one supplier's documents."""
    query = (
        select(DiscrepancyRow, DocumentRow.filename)
        .join(DocumentRow, DocumentRow.id == DiscrepancyRow.document_id)
        .outerjoin(InvoiceRow, InvoiceRow.document_id == DiscrepancyRow.document_id)
        .outerjoin(DeliveryNoteRow, DeliveryNoteRow.document_id == DiscrepancyRow.document_id)
        .where(DiscrepancyRow.owner_id == owner_id)
        .order_by(DocumentRow.filename, DiscrepancyRow.rule)
    )
    if status != "any":
        query = query.where(DiscrepancyRow.status == status)
    if supplier:
        pattern = _contains(supplier)
        query = query.where(
            or_(
                InvoiceRow.supplier_name.ilike(pattern, escape="\\"),
                DeliveryNoteRow.supplier_name.ilike(pattern, escape="\\"),
            )
        )
    return [
        FindingSummary(
            discrepancy_id=row.id,
            document_id=row.document_id,
            filename=filename,
            rule=row.rule,
            type=row.type,
            message=row.message,
            amount_impact=row.amount_impact,
            status=row.status,
        )
        for row, filename in session.execute(query)
    ]
