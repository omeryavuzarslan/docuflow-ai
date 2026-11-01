"""Inject exactly one labelled error into a clean set.

Rules (CLAUDE.md):
- quantity / unit price mismatch: change the value and recompute that line and the totals,
  so the invoice is internally consistent and the only problem is the mismatch with DN/PO.
- line total / VAT / total error: change only that one field; nothing is recomputed.
- duplicate invoice: an exact copy with a new document id.

Only the invoice is ever changed. Field paths use zero-based tuple indexes, matching the
JSON arrays: "lines[2].quantity" is the third line.
"""

import random
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel

from backend.app.domain.calculations import PENNY, invoice_totals, line_net, line_vat
from backend.app.domain.document_set import DocumentSet
from backend.app.domain.documents import Invoice, InvoiceLine
from backend.app.domain.errors import ErrorType, InjectedError
from data_generator.catalog import SUPPLIERS

PRODUCTS_BY_SKU = {p.sku: p for entry in SUPPLIERS for p in entry.products}

# Arithmetic errors are at least 50p. A 1p difference could be a legitimate rounding
# method (ADR-0001), so it would not be a fair "error" to ask the system to find.
MIN_ERROR_PENCE, MAX_ERROR_PENCE = 50, 2000


def inject_error(doc_set: DocumentSet, error_type: ErrorType, rng: random.Random) -> DocumentSet:
    invoice = doc_set.invoices[0]
    injector = _INJECTORS[error_type]
    new_invoices, error = injector(doc_set, invoice, rng)
    return evolve(doc_set, invoices=new_invoices, errors=(*doc_set.errors, error))


def evolve[M: BaseModel](model: M, **changes: Any) -> M:
    """Like `model_copy(update=...)`, but validated.

    `model_copy` skips validation, so a bad value (or a Decimal at the wrong scale) would
    slip into the ground truth unnoticed. Rebuilding through `model_validate` runs every
    check again.
    """
    return type(model).model_validate({**model.model_dump(), **changes})


Injector = Callable[
    [DocumentSet, Invoice, random.Random], tuple[tuple[Invoice, ...], InjectedError]
]


def _quantity_mismatch(
    doc_set: DocumentSet, invoice: Invoice, rng: random.Random
) -> tuple[tuple[Invoice, ...], InjectedError]:
    i = rng.randrange(len(invoice.lines))
    line = invoice.lines[i]
    step = PRODUCTS_BY_SKU[line.sku].qty_step
    delivered = next(
        dn.quantity_delivered for dn in doc_set.delivery_note.lines if dn.sku == line.sku
    )
    new_invoice = _recompute_line(invoice, i, quantity=delivered + step * rng.randint(1, 5))
    error = InjectedError(
        type=ErrorType.QUANTITY_MISMATCH,
        document_id=invoice.document_id,
        field=f"lines[{i}].quantity",
        expected=str(delivered),
        actual=str(new_invoice.lines[i].quantity),
    )
    return (new_invoice,), error


def _unit_price_mismatch(
    doc_set: DocumentSet, invoice: Invoice, rng: random.Random
) -> tuple[tuple[Invoice, ...], InjectedError]:
    i = rng.randrange(len(invoice.lines))
    old = invoice.lines[i].unit_price
    raised = old * (100 + rng.randint(5, 15)) / 100
    # Prefer a whole-penny price as a real supplier would quote; fall back to 4 places
    # when a sub-penny price would round back to the original.
    new = raised.quantize(PENNY, rounding=ROUND_HALF_UP)
    if new == old:
        new = raised.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    new_invoice = _recompute_line(invoice, i, unit_price=new)
    error = InjectedError(
        type=ErrorType.UNIT_PRICE_MISMATCH,
        document_id=invoice.document_id,
        field=f"lines[{i}].unit_price",
        expected=str(old),
        actual=str(new_invoice.lines[i].unit_price),
    )
    return (new_invoice,), error


def _line_total_error(
    doc_set: DocumentSet, invoice: Invoice, rng: random.Random
) -> tuple[tuple[Invoice, ...], InjectedError]:
    return _set_line_field(invoice, rng, "line_net", ErrorType.LINE_TOTAL_ERROR)


def _vat_error(
    doc_set: DocumentSet, invoice: Invoice, rng: random.Random
) -> tuple[tuple[Invoice, ...], InjectedError]:
    return _set_line_field(invoice, rng, "line_vat", ErrorType.VAT_ERROR)


def _total_error(
    doc_set: DocumentSet, invoice: Invoice, rng: random.Random
) -> tuple[tuple[Invoice, ...], InjectedError]:
    old = invoice.gross_total
    new_invoice = evolve(invoice, gross_total=_wrong_amount(old, rng))
    error = InjectedError(
        type=ErrorType.TOTAL_ERROR,
        document_id=invoice.document_id,
        field="gross_total",
        expected=str(old),
        actual=str(new_invoice.gross_total),
    )
    return (new_invoice,), error


def _duplicate_invoice(
    doc_set: DocumentSet, invoice: Invoice, rng: random.Random
) -> tuple[tuple[Invoice, ...], InjectedError]:
    duplicate = evolve(invoice, document_id=invoice.document_id.replace("-inv-1", "-inv-2"))
    error = InjectedError(
        type=ErrorType.DUPLICATE_INVOICE,
        document_id=duplicate.document_id,
        field=None,
        related_document_id=invoice.document_id,
    )
    return (invoice, duplicate), error


_INJECTORS: dict[ErrorType, Injector] = {
    ErrorType.QUANTITY_MISMATCH: _quantity_mismatch,
    ErrorType.UNIT_PRICE_MISMATCH: _unit_price_mismatch,
    ErrorType.LINE_TOTAL_ERROR: _line_total_error,
    ErrorType.VAT_ERROR: _vat_error,
    ErrorType.TOTAL_ERROR: _total_error,
    ErrorType.DUPLICATE_INVOICE: _duplicate_invoice,
}


def _recompute_line(invoice: Invoice, index: int, **changes: Decimal) -> Invoice:
    """Change a line's quantity or price, then recompute that line and the totals."""
    line = evolve(invoice.lines[index], **changes)
    net = line_net(line.quantity, line.unit_price)
    line = evolve(line, line_net=net, line_vat=line_vat(net, line.vat_rate))
    lines = _replace(invoice.lines, index, line)
    totals = invoice_totals(lines)
    return evolve(
        invoice,
        lines=lines,
        net_total=totals.net,
        vat_total=totals.vat,
        gross_total=totals.gross,
    )


def _set_line_field(
    invoice: Invoice, rng: random.Random, field: str, error_type: ErrorType
) -> tuple[tuple[Invoice, ...], InjectedError]:
    """Change one money field on one line and nothing else."""
    i = rng.randrange(len(invoice.lines))
    old: Decimal = getattr(invoice.lines[i], field)
    line = evolve(invoice.lines[i], **{field: _wrong_amount(old, rng)})
    new_invoice = evolve(invoice, lines=_replace(invoice.lines, i, line))
    error = InjectedError(
        type=error_type,
        document_id=invoice.document_id,
        field=f"lines[{i}].{field}",
        expected=str(old),
        actual=str(getattr(new_invoice.lines[i], field)),
    )
    return (new_invoice,), error


def _wrong_amount(correct: Decimal, rng: random.Random) -> Decimal:
    """Off by 0.50-20.00 in either direction, never below zero."""
    delta = Decimal(rng.randint(MIN_ERROR_PENCE, MAX_ERROR_PENCE)).scaleb(-2)
    if rng.randint(0, 1) and correct - delta >= 0:
        return correct - delta
    return correct + delta


def _replace(
    lines: tuple[InvoiceLine, ...], index: int, line: InvoiceLine
) -> tuple[InvoiceLine, ...]:
    return (*lines[:index], line, *lines[index + 1 :])
