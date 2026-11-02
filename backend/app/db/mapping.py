"""Explicit conversion between domain models and table rows.

Written out by hand rather than generated, so every column is a visible decision. The
round-trip test (tests/integration/db/test_schema.py) fails if a field is added on one side
and forgotten on the other.
"""

from typing import Any

from backend.app.db.models import (
    DeliveryNoteRow,
    DNLineRow,
    InvoiceLineRow,
    InvoiceRow,
    POLineRow,
    PurchaseOrderRow,
)
from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder
from backend.app.domain.parties import Party

Document = PurchaseOrder | DeliveryNote | Invoice
DocumentRowType = PurchaseOrderRow | DeliveryNoteRow | InvoiceRow

ROW_CLASSES: dict[str, type[DocumentRowType]] = {
    "purchase_order": PurchaseOrderRow,
    "delivery_note": DeliveryNoteRow,
    "invoice": InvoiceRow,
}


def _party_columns(prefix: str, party: Party) -> dict[str, Any]:
    return {
        f"{prefix}_name": party.name,
        f"{prefix}_vat_number": party.vat_number,
        f"{prefix}_address_line1": party.address.line1,
        f"{prefix}_address_line2": party.address.line2,
        f"{prefix}_city": party.address.city,
        f"{prefix}_postcode": party.address.postcode,
        f"{prefix}_country": party.address.country,
    }


def _party_dict(prefix: str, row: DocumentRowType) -> dict[str, Any]:
    def col(name: str) -> Any:
        return getattr(row, f"{prefix}_{name}")

    return {
        "name": col("name"),
        "vat_number": col("vat_number"),
        "address": {
            "line1": col("address_line1"),
            "line2": col("address_line2"),
            "city": col("city"),
            "postcode": col("postcode"),
            "country": col("country"),
        },
    }


def document_to_row(document: Document, owner_id: str) -> DocumentRowType:
    common: dict[str, Any] = {
        "document_id": document.document_id,
        "owner_id": owner_id,
        **_party_columns("supplier", document.supplier),
        **_party_columns("buyer", document.buyer),
    }
    if isinstance(document, PurchaseOrder):
        return PurchaseOrderRow(
            **common,
            po_number=document.po_number,
            issue_date=document.issue_date,
            currency=document.currency,
            net_total=document.net_total,
            lines=[
                POLineRow(
                    position=i,
                    line_no=line.line_no,
                    sku=line.sku,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    vat_rate=line.vat_rate,
                    line_net=line.line_net,
                )
                for i, line in enumerate(document.lines)
            ],
        )
    if isinstance(document, DeliveryNote):
        return DeliveryNoteRow(
            **common,
            dn_number=document.dn_number,
            po_number=document.po_number,
            delivery_date=document.delivery_date,
            lines=[
                DNLineRow(
                    position=i,
                    line_no=line.line_no,
                    sku=line.sku,
                    description=line.description,
                    quantity_delivered=line.quantity_delivered,
                )
                for i, line in enumerate(document.lines)
            ],
        )
    return InvoiceRow(
        **common,
        invoice_number=document.invoice_number,
        po_number=document.po_number,
        delivery_note_numbers=list(document.delivery_note_numbers),
        issue_date=document.issue_date,
        due_date=document.due_date,
        currency=document.currency,
        net_total=document.net_total,
        vat_total=document.vat_total,
        gross_total=document.gross_total,
        lines=[
            InvoiceLineRow(
                position=i,
                line_no=line.line_no,
                sku=line.sku,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
                line_net=line.line_net,
                line_vat=line.line_vat,
            )
            for i, line in enumerate(document.lines)
        ],
    )


def document_from_row(row: DocumentRowType) -> Document:
    """Rebuild the domain document; Pydantic validation runs again on the way out."""
    common: dict[str, Any] = {
        "document_id": row.document_id,
        "supplier": _party_dict("supplier", row),
        "buyer": _party_dict("buyer", row),
    }
    line_fields = ("line_no", "sku", "description")
    if isinstance(row, PurchaseOrderRow):
        return PurchaseOrder.model_validate(
            {
                **common,
                "po_number": row.po_number,
                "issue_date": row.issue_date,
                "currency": row.currency,
                "net_total": row.net_total,
                "lines": [
                    {
                        **{f: getattr(line, f) for f in line_fields},
                        "quantity": line.quantity,
                        "unit_price": line.unit_price,
                        "vat_rate": line.vat_rate,
                        "line_net": line.line_net,
                    }
                    for line in row.lines
                ],
            }
        )
    if isinstance(row, DeliveryNoteRow):
        return DeliveryNote.model_validate(
            {
                **common,
                "dn_number": row.dn_number,
                "po_number": row.po_number,
                "delivery_date": row.delivery_date,
                "lines": [
                    {
                        **{f: getattr(line, f) for f in line_fields},
                        "quantity_delivered": line.quantity_delivered,
                    }
                    for line in row.lines
                ],
            }
        )
    return Invoice.model_validate(
        {
            **common,
            "invoice_number": row.invoice_number,
            "po_number": row.po_number,
            "delivery_note_numbers": tuple(row.delivery_note_numbers),
            "issue_date": row.issue_date,
            "due_date": row.due_date,
            "currency": row.currency,
            "net_total": row.net_total,
            "vat_total": row.vat_total,
            "gross_total": row.gross_total,
            "lines": [
                {
                    **{f: getattr(line, f) for f in line_fields},
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "vat_rate": line.vat_rate,
                    "line_net": line.line_net,
                    "line_vat": line.line_vat,
                }
                for line in row.lines
            ],
        }
    )
