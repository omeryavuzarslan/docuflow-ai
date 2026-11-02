"""What the LLM returns: every value as text, copied exactly as printed on the document.

This is a raw mirror of the domain models (backend/app/domain/documents.py), not a second
source of truth: `normalise.to_domain` turns it into a domain document, and a round-trip
test checks that every domain field can be read off a page and converted back.

Why strings? The LLM only copies; Python parses "£1,234.56" into Decimal. That keeps every
number exactly as printed (no float, no LLM arithmetic) and keeps the raw extraction
separate from the converted, later human-corrected, values.

One flat schema covers all three document types (plus "other"), so a single call both
classifies the document and extracts it. Field descriptions go into the JSON schema the
model sees.

Absent values are empty strings, not null: every `str | None` becomes an `anyOf` in the
JSON schema, and with ~40 of them the API rejects the schema as too complex. For the same
reason every field is *required* in the schema the model sees (the API limits optional
fields), while Python code can still omit them thanks to the defaults.
"""

from typing import Literal

from pydantic import Field

from backend.app.llm.schema import LLMOutput

DocType = Literal["purchase_order", "delivery_note", "invoice", "other"]


_AS_PRINTED = "Copied exactly as printed, including any currency symbol; empty if absent."


class ExtractedParty(LLMOutput):
    name: str = ""
    vat_number: str = Field(default="", description="VAT registration number as printed.")
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    postcode: str = ""


class ExtractedLine(LLMOutput):
    line_no: str = ""
    sku: str = Field(default="", description="Item / product code.")
    description: str = ""
    quantity: str = Field(
        default="",
        description="Quantity as printed. On a delivery note: the quantity delivered.",
    )
    unit_price: str = Field(default="", description=_AS_PRINTED)
    vat_rate: str = Field(default="", description="VAT rate as printed, e.g. '20%'.")
    line_net: str = Field(default="", description="Net line amount. " + _AS_PRINTED)
    line_vat: str = Field(default="", description="VAT amount of the line. " + _AS_PRINTED)


class ExtractedDocument(LLMOutput):
    doc_type: DocType
    document_number: str = Field(
        default="",
        description=(
            "This document's own number: PO number, delivery note number or invoice number."
        ),
    )
    po_reference: str = Field(
        default="",
        description=(
            "The purchase order this document refers to (delivery notes and invoices only)."
        ),
    )
    delivery_note_references: tuple[str, ...] = Field(
        default=(), description="Delivery note numbers an invoice refers to."
    )
    issue_date: str = Field(
        default="",
        description=(
            "Order date (PO), delivery/shipped date (delivery note) or invoice date, as printed."
        ),
    )
    due_date: str = Field(default="", description="Payment due date (invoices), as printed.")
    currency: str = Field(default="", description="ISO currency code, e.g. GBP.")
    supplier: ExtractedParty = Field(
        default_factory=ExtractedParty,
        description="The company selling the goods. On a purchase order it is the recipient.",
    )
    buyer: ExtractedParty = Field(
        default_factory=ExtractedParty,
        description="The company buying the goods. On a purchase order it is the issuer.",
    )
    lines: tuple[ExtractedLine, ...] = ()
    net_total: str = Field(default="", description="Total before VAT. " + _AS_PRINTED)
    vat_total: str = Field(default="", description="Total VAT. " + _AS_PRINTED)
    gross_total: str = Field(
        default="", description="Total including VAT / amount due. " + _AS_PRINTED
    )
