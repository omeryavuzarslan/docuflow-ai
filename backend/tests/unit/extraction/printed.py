"""Build the ExtractedDocument a perfect reader would return for a domain document:
every value copied exactly as the PDF prints it."""

from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder
from backend.app.domain.parties import Party
from backend.app.extraction.schema import ExtractedDocument, ExtractedLine, ExtractedParty
from data_generator.render import (
    format_date,
    format_money,
    format_price,
    format_quantity,
    format_vat_rate,
)


def _party(party: Party) -> ExtractedParty:
    return ExtractedParty(
        name=party.name,
        vat_number=party.vat_number,
        address_line1=party.address.line1,
        address_line2=party.address.line2 or "",
        city=party.address.city,
        postcode=party.address.postcode,
    )


def printed(document: PurchaseOrder | DeliveryNote | Invoice) -> ExtractedDocument:
    supplier, buyer = _party(document.supplier), _party(document.buyer)
    if isinstance(document, PurchaseOrder):
        return ExtractedDocument(
            doc_type="purchase_order",
            document_number=document.po_number,
            issue_date=format_date(document.issue_date),
            currency="GBP",
            lines=tuple(
                ExtractedLine(
                    line_no=str(line.line_no),
                    sku=line.sku,
                    description=line.description,
                    quantity=format_quantity(line.quantity),
                    unit_price=format_price(line.unit_price),
                    vat_rate=format_vat_rate(line.vat_rate),
                    line_net=format_money(line.line_net),
                )
                for line in document.lines
            ),
            net_total=format_money(document.net_total),
            supplier=supplier,
            buyer=buyer,
        )
    if isinstance(document, DeliveryNote):
        return ExtractedDocument(
            doc_type="delivery_note",
            document_number=document.dn_number,
            po_reference=document.po_number,
            issue_date=format_date(document.delivery_date),
            lines=tuple(
                ExtractedLine(
                    line_no=str(line.line_no),
                    sku=line.sku,
                    description=line.description,
                    quantity=format_quantity(line.quantity_delivered),
                )
                for line in document.lines
            ),
            supplier=supplier,
            buyer=buyer,
        )
    return ExtractedDocument(
        doc_type="invoice",
        document_number=document.invoice_number,
        po_reference=document.po_number,
        delivery_note_references=document.delivery_note_numbers,
        issue_date=format_date(document.issue_date),
        due_date=format_date(document.due_date),
        currency="GBP",
        lines=tuple(
            ExtractedLine(
                line_no=str(line.line_no),
                sku=line.sku,
                description=line.description,
                quantity=format_quantity(line.quantity),
                unit_price=format_price(line.unit_price),
                vat_rate=format_vat_rate(line.vat_rate),
                line_net=format_money(line.line_net),
                line_vat=format_money(line.line_vat),
            )
            for line in document.lines
        ),
        net_total=format_money(document.net_total),
        vat_total=format_money(document.vat_total),
        gross_total=format_money(document.gross_total),
        supplier=supplier,
        buyer=buyer,
    )
