"""Turn the LLM's as-printed strings into typed domain documents. Deterministic Python only.

The parsers are strict: they accept the formats documents actually use and raise on
anything else. They never "repair" OCR mistakes (e.g. "£o.027"); a field that cannot be
parsed is reported as an error so it can be shown for human review.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from backend.app.domain.documents import (
    DeliveryNote,
    Invoice,
    PurchaseOrder,
)
from backend.app.extraction.schema import ExtractedDocument, ExtractedParty

Document = PurchaseOrder | DeliveryNote | Invoice

# Digits with optional thousands commas (every group exactly 3 digits) and decimals.
_NUMBER = re.compile(r"-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?")
_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%d-%m-%Y", "%d.%m.%Y")


def parse_amount(text: str) -> Decimal:
    """'£1,234.56' -> Decimal('1234.56'). Currency marks and spaces are dropped."""
    cleaned = text.replace("£", "").replace("GBP", "")
    return _parse_number(cleaned, original=text)


def parse_quantity(text: str) -> Decimal:
    """'1,400' -> Decimal('1400'). No currency allowed."""
    return _parse_number(text, original=text)


def parse_rate(text: str) -> Decimal:
    """'20%', '20' or '0.20' -> Decimal('0.20')."""
    has_percent = "%" in text
    value = _parse_number(text.replace("%", ""), original=text)
    return value / 100 if has_percent or value > 1 else value


def parse_date(text: str) -> date:
    """UK documents: day first. Also ISO and '6 March 2026'."""
    cleaned = " ".join(text.split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {text!r}")


def _parse_number(cleaned: str, original: str) -> Decimal:
    compact = "".join(cleaned.split())
    if not _NUMBER.fullmatch(compact):
        raise ValueError(f"not a number: {original!r}")
    try:
        return Decimal(compact.replace(",", ""))
    except InvalidOperation as exc:  # pragma: no cover - the regex already guards this
        raise ValueError(f"not a number: {original!r}") from exc


class _Collector:
    """Parses fields one by one and records every failure, so one bad value does not hide
    the others."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def get(self, path: str, value: str, parser: Any = None) -> Any:
        if not value.strip():
            self.errors.append(f"{path}: missing")
            return None
        if parser is None:
            return value.strip()
        try:
            return parser(value)
        except ValueError as exc:
            self.errors.append(f"{path}: {exc}")
            return None

    def party(self, path: str, party: ExtractedParty) -> dict[str, Any]:
        return {
            "name": self.get(f"{path}.name", party.name),
            "vat_number": self.get(f"{path}.vat_number", party.vat_number),
            "address": {
                "line1": self.get(f"{path}.address_line1", party.address_line1),
                "line2": party.address_line2.strip() or None,
                "city": self.get(f"{path}.city", party.city),
                "postcode": self.get(f"{path}.postcode", party.postcode),
            },
        }


def to_domain(raw: ExtractedDocument, document_id: str) -> tuple[Document | None, tuple[str, ...]]:
    """(domain document, ()) on success, or (None, errors) listing every field that failed."""
    if raw.doc_type == "other":
        return None, ("doc_type: not a purchase order, delivery note or invoice",)

    c = _Collector()
    if raw.currency.strip() and raw.currency.strip().upper() not in ("GBP", "£"):
        c.errors.append(f"currency: unsupported {raw.currency!r}")

    data: dict[str, Any] = {
        "document_id": document_id,
        "supplier": c.party("supplier", raw.supplier),
        "buyer": c.party("buyer", raw.buyer),
    }
    lines: list[dict[str, Any]] = []
    for i, line in enumerate(raw.lines):
        p = f"lines[{i}]"
        item: dict[str, Any] = {
            "line_no": _line_no(line.line_no, i),
            "sku": c.get(f"{p}.sku", line.sku),
            "description": c.get(f"{p}.description", line.description),
        }
        if raw.doc_type == "delivery_note":
            item["quantity_delivered"] = c.get(f"{p}.quantity", line.quantity, parse_quantity)
        else:
            item["quantity"] = c.get(f"{p}.quantity", line.quantity, parse_quantity)
            item["unit_price"] = c.get(f"{p}.unit_price", line.unit_price, parse_amount)
            item["vat_rate"] = c.get(f"{p}.vat_rate", line.vat_rate, parse_rate)
            item["line_net"] = c.get(f"{p}.line_net", line.line_net, parse_amount)
            if raw.doc_type == "invoice":
                item["line_vat"] = c.get(f"{p}.line_vat", line.line_vat, parse_amount)
        lines.append(item)
    data["lines"] = lines

    if raw.doc_type == "purchase_order":
        model: type[Document] = PurchaseOrder
        data["po_number"] = c.get("document_number", raw.document_number)
        data["issue_date"] = c.get("issue_date", raw.issue_date, parse_date)
        data["net_total"] = c.get("net_total", raw.net_total, parse_amount)
    elif raw.doc_type == "delivery_note":
        model = DeliveryNote
        data["dn_number"] = c.get("document_number", raw.document_number)
        data["po_number"] = c.get("po_reference", raw.po_reference)
        data["delivery_date"] = c.get("issue_date", raw.issue_date, parse_date)
    else:
        model = Invoice
        data["invoice_number"] = c.get("document_number", raw.document_number)
        data["po_number"] = c.get("po_reference", raw.po_reference)
        data["delivery_note_numbers"] = tuple(r.strip() for r in raw.delivery_note_references)
        data["issue_date"] = c.get("issue_date", raw.issue_date, parse_date)
        data["due_date"] = c.get("due_date", raw.due_date, parse_date)
        data["net_total"] = c.get("net_total", raw.net_total, parse_amount)
        data["vat_total"] = c.get("vat_total", raw.vat_total, parse_amount)
        data["gross_total"] = c.get("gross_total", raw.gross_total, parse_amount)

    if c.errors:
        return None, tuple(c.errors)
    try:
        return model.model_validate(data), ()
    except ValidationError as exc:
        # Values that parsed but break a domain rule (e.g. 3 decimal places on a total).
        return None, tuple(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()
        )


def _line_no(text: str, index: int) -> int:
    """The printed line number if there is a usable one, else the position on the page."""
    if text.strip().isdigit() and int(text) >= 1:
        return int(text)
    return index + 1
