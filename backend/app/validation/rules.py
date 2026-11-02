"""Deterministic discrepancy rules. Every decision here is plain Decimal arithmetic.

Order-level rules (need the matched PO / delivery notes):
  R1 quantity:  invoiced more than delivered (minus what earlier invoices already billed)
  R2 price:     unit price differs from the purchase order
Invoice arithmetic (run on every invoice, matched or not):
  R3 line net   R4 line VAT   R5 VAT total   R6 net total   R7 gross = net + VAT
Across invoices:
  R8 duplicate: same supplier and invoice number as an earlier invoice
Matching:
  M1 a delivery note or invoice that matches no purchase order

Documents still under review (`incomplete`) are not judged on missing evidence: an invoice
whose PO is under review is held instead of flagged as unmatched, and R1 is held for an
order whose delivery notes are not all readable.

Tolerances follow HMRC VAT Notice 700 section 17.5 and are explained in ADR-0002. Each
problem is reported once, where it starts: a wrong line net is not reported again as a
wrong net total, a wrong line VAT not again as a wrong VAT total, and a duplicate invoice
is not also checked as if it were a second bill.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from itertools import product

from backend.app.domain.calculations import PENNY, round_money
from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder
from backend.app.matching.match import MatchGroup, invoice_order, match_documents, sku_key
from backend.app.validation.models import Discrepancy, DiscrepancyType, IncompleteDocument

Document = PurchaseOrder | DeliveryNote | Invoice

T = DiscrepancyType


@dataclass(frozen=True)
class ValidationReport:
    discrepancies: list[Discrepancy]
    groups: tuple[MatchGroup, ...]
    held: list[str]  # checks not run because a document they need is under review


def validate(
    documents: Iterable[Document],
    incomplete: Iterable[IncompleteDocument] = (),
    received_order: Mapping[str, int] | None = None,
) -> ValidationReport:
    """`received_order` ({document_id: arrival rank}) decides which of two identical
    invoices is the original; without it, the document id breaks ties."""
    docs = list(documents)
    pending = list(incomplete)
    pending_orders = {_ref(p.po_number) for p in pending if p.doc_type == "purchase_order"}
    pending_deliveries = {_ref(p.po_number) for p in pending if p.doc_type == "delivery_note"}
    held: list[str] = []
    order = received_order or {}
    match = match_documents(docs, order)
    invoices = sorted(
        (d for d in docs if isinstance(d, Invoice)), key=lambda i: invoice_order(i, order)
    )
    duplicates = _duplicates(invoices)

    found: list[Discrepancy] = []
    for doc in match.unmatched:
        if _ref(doc.po_number) in pending_orders:
            held.append(f"{doc.document_id}: matching held, PO {doc.po_number} is under review")
            continue
        found.append(
            Discrepancy(
                rule="M1",
                type=T.UNMATCHED_DOCUMENT,
                document_id=doc.document_id,
                field="po_number",
                actual=doc.po_number,
                message=f"No purchase order {doc.po_number} from {doc.supplier.name}.",
            )
        )
    for duplicate_id, original in duplicates.items():
        found.append(
            Discrepancy(
                rule="R8",
                type=T.DUPLICATE_INVOICE,
                document_id=duplicate_id,
                field=None,
                related_document_id=original.document_id,
                amount_impact=original.gross_total,
                message=(
                    f"Invoice {original.invoice_number} from {original.supplier.name} "
                    f"was already received ({original.document_id})."
                ),
            )
        )
    for invoice in invoices:
        if invoice.document_id not in duplicates:
            found.extend(check_invoice_arithmetic(invoice))
    for group in match.groups:
        po_number = group.purchase_order.po_number
        deliveries_known = _ref(po_number) not in pending_deliveries
        if not deliveries_known:
            held.append(f"{po_number}: quantity check held, a delivery note is under review")
        found.extend(check_order(group, skip=duplicates.keys(), check_quantities=deliveries_known))

    found.sort(key=lambda d: (d.document_id, d.rule, d.field or ""))
    return ValidationReport(discrepancies=found, groups=match.groups, held=held)


def _ref(reference: str) -> str:
    return "".join(reference.split()).upper()


# --- order-level rules ---------------------------------------------------------------


def check_order(
    group: MatchGroup, skip: Iterable[str] = (), check_quantities: bool = True
) -> Iterator[Discrepancy]:
    skipped = set(skip)
    ordered = {sku_key(line.sku): line for line in group.purchase_order.lines}
    remaining = group.delivered_by_sku()  # what may still be billed
    for invoice in group.invoices:
        if invoice.document_id in skipped:
            continue
        for i, line in enumerate(invoice.lines):
            key = sku_key(line.sku)
            allowed = remaining.get(key, Decimal(0))
            if check_quantities and line.quantity > allowed:  # R1; up to delivered is fine
                extra = line.quantity - allowed
                yield Discrepancy(
                    rule="R1",
                    type=T.QUANTITY_MISMATCH,
                    document_id=invoice.document_id,
                    field=f"lines[{i}].quantity",
                    expected=str(allowed),
                    actual=str(line.quantity),
                    amount_impact=round_money(extra * line.unit_price),
                    message=(
                        f"{line.sku}: invoiced {_qty(line.quantity)}, but only "
                        f"{_qty(allowed)} delivered and not yet invoiced."
                    ),
                )
            remaining[key] = max(Decimal(0), allowed - line.quantity)

            po_line = ordered.get(key)
            if po_line is not None and line.unit_price != po_line.unit_price:  # R2
                yield Discrepancy(
                    rule="R2",
                    type=T.UNIT_PRICE_MISMATCH,
                    document_id=invoice.document_id,
                    field=f"lines[{i}].unit_price",
                    expected=str(po_line.unit_price),
                    actual=str(line.unit_price),
                    amount_impact=round_money(
                        (line.unit_price - po_line.unit_price) * line.quantity
                    ),
                    message=(
                        f"{line.sku}: price {line.unit_price} differs from the ordered "
                        f"{po_line.unit_price}."
                    ),
                )


# --- invoice arithmetic --------------------------------------------------------------


def check_invoice_arithmetic(invoice: Invoice) -> Iterator[Discrepancy]:
    doc = invoice.document_id
    true_nets = [line.quantity * line.unit_price for line in invoice.lines]  # unrounded

    for i, (line, true_net) in enumerate(zip(invoice.lines, true_nets, strict=True)):
        if abs(line.line_net - true_net) >= PENNY:  # R3
            yield _money_finding(
                "R3",
                T.LINE_TOTAL_ERROR,
                doc,
                f"lines[{i}].line_net",
                round_money(true_net),
                line.line_net,
                f"{line.sku}: {_qty(line.quantity)} x {line.unit_price} "
                f"is {round_money(true_net)}, not {line.line_net}.",
            )
        # The VAT may be computed on the printed net or, if that net is itself wrong (R3),
        # on the correct one; either way it is not a second, separate VAT error.
        allowed = acceptable_vat(line.line_net, line.vat_rate) | acceptable_vat(
            round_money(true_net), line.vat_rate
        )
        if line.line_vat not in allowed:  # R4
            yield _money_finding(
                "R4",
                T.VAT_ERROR,
                doc,
                f"lines[{i}].line_vat",
                round_money(line.line_net * line.vat_rate),
                line.line_vat,
                f"{line.sku}: VAT at {line.vat_rate:.0%} on {line.line_net} cannot be "
                f"{line.line_vat}.",
            )

    if invoice.vat_total not in acceptable_vat_totals(invoice):  # R5
        expected = sum(
            (round_money(line.line_net * line.vat_rate) for line in invoice.lines), Decimal(0)
        )
        yield _money_finding(
            "R5",
            T.VAT_ERROR,
            doc,
            "vat_total",
            expected,
            invoice.vat_total,
            f"VAT total {invoice.vat_total} matches neither the line VATs nor the "
            f"invoice-level calculation ({expected}).",
        )

    printed_net = sum((line.line_net for line in invoice.lines), Decimal(0))
    correct_net = sum((round_money(n) for n in true_nets), Decimal(0))
    # If the total agrees with the correct line amounts, the fault is in a line (R3).
    if invoice.net_total not in (printed_net, correct_net):  # R6
        yield _money_finding(
            "R6",
            T.TOTAL_ERROR,
            doc,
            "net_total",
            printed_net,
            invoice.net_total,
            f"Net total {invoice.net_total} is not the sum of the lines ({printed_net}).",
        )

    if invoice.gross_total != invoice.net_total + invoice.vat_total:  # R7
        expected = invoice.net_total + invoice.vat_total
        yield _money_finding(
            "R7",
            T.TOTAL_ERROR,
            doc,
            "gross_total",
            expected,
            invoice.gross_total,
            f"Total {invoice.gross_total} is not net {invoice.net_total} + VAT "
            f"{invoice.vat_total} = {expected}.",
        )


def acceptable_vat(net: Decimal, rate: Decimal) -> set[Decimal]:
    """VAT amounts HMRC allows for one calculation: to the nearest penny, or down
    (VAT Notice 700, 17.5.1)."""
    exact = net * rate
    return {round_money(exact), exact.quantize(PENNY, rounding=ROUND_DOWN)}


def acceptable_vat_totals(invoice: Invoice) -> set[Decimal]:
    """VAT totals consistent with the invoice under any permitted method:
    the sum of the printed line VATs, the sum of correctly rounded line VATs (nearest or
    down), or one calculation per VAT rate on the summed nets (nearest or down)."""
    totals = {sum((line.line_vat for line in invoice.lines), Decimal(0))}
    for rounding in (round_money, _round_down):
        totals.add(
            sum((rounding(line.line_net * line.vat_rate) for line in invoice.lines), Decimal(0))
        )

    net_by_rate: dict[Decimal, Decimal] = defaultdict(Decimal)
    for line in invoice.lines:
        net_by_rate[line.vat_rate] += line.line_net
    per_rate = [sorted(acceptable_vat(net, rate)) for rate, net in net_by_rate.items()]
    totals.update(sum(choice, Decimal(0)) for choice in product(*per_rate))
    return totals


def _round_down(value: Decimal) -> Decimal:
    return value.quantize(PENNY, rounding=ROUND_DOWN)


# --- duplicates ----------------------------------------------------------------------


def _duplicates(invoices: list[Invoice]) -> dict[str, Invoice]:
    """{duplicate document_id: the earlier original}. `invoices` must be in date order."""
    seen: dict[tuple[str, str], Invoice] = {}
    duplicates: dict[str, Invoice] = {}
    for invoice in invoices:
        key = (
            "".join(invoice.supplier.vat_number.split()).upper(),
            "".join(invoice.invoice_number.split()).upper(),
        )
        if key in seen:
            duplicates[invoice.document_id] = seen[key]
        else:
            seen[key] = invoice
    return duplicates


# --- helpers -------------------------------------------------------------------------


def _money_finding(
    rule: str,
    kind: DiscrepancyType,
    document_id: str,
    field: str,
    expected: Decimal,
    actual: Decimal,
    message: str,
) -> Discrepancy:
    return Discrepancy(
        rule=rule,
        type=kind,
        document_id=document_id,
        field=field,
        expected=str(expected),
        actual=str(actual),
        amount_impact=actual - expected,
        message=message,
    )


def _qty(value: Decimal) -> str:
    return f"{value.normalize():f}"
