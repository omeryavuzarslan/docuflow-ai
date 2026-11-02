from decimal import Decimal
from enum import StrEnum

from backend.app.domain.types import DomainModel


class DiscrepancyType(StrEnum):
    # The first six share their values with domain.errors.ErrorType, so a finding can be
    # compared with an injected error directly.
    QUANTITY_MISMATCH = "quantity_mismatch"
    UNIT_PRICE_MISMATCH = "unit_price_mismatch"
    LINE_TOTAL_ERROR = "line_total_error"
    VAT_ERROR = "vat_error"
    TOTAL_ERROR = "total_error"
    DUPLICATE_INVOICE = "duplicate_invoice"
    UNMATCHED_DOCUMENT = "unmatched_document"


class Discrepancy(DomainModel):
    """One finding, with enough evidence for a person to check it in seconds."""

    rule: str  # "R1".."R8", "M1"
    type: DiscrepancyType
    document_id: str
    field: str | None  # e.g. "lines[1].quantity"; None for whole-document findings
    expected: str | None = None
    actual: str | None = None
    related_document_id: str | None = None  # the original, for a duplicate
    # Net money effect in GBP (positive = the supplier asks for too much); None if unknown.
    amount_impact: Decimal | None = None
    message: str


class IncompleteDocument(DomainModel):
    """A document that was read but could not be fully converted (it is with a person for
    review). Only what is needed to know which checks depend on it."""

    document_id: str
    doc_type: str  # "purchase_order" | "delivery_note" | "invoice" | "other"
    po_number: str  # its own number for a PO, the referenced PO otherwise; "" if unreadable
