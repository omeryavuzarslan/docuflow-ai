"""Build one clean, internally consistent PO -> DN -> invoice set.

The order of random draws is part of the output: changing it changes every set for a
given seed. Keep new draws at the end, or accept that the dataset changes.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from backend.app.domain.calculations import invoice_totals, line_net, line_vat
from backend.app.domain.document_set import DocumentSet
from backend.app.domain.documents import (
    DeliveryNote,
    DNLine,
    Invoice,
    InvoiceLine,
    POLine,
    PurchaseOrder,
)
from data_generator.catalog import BUYERS, SUPPLIERS, Product
from data_generator.plan import SetPlan
from data_generator.rng import make_rng, random_decimal

VAT_RATE = Decimal("0.20")
BASE_DATE = date(2026, 1, 1)
PAYMENT_TERMS_DAYS = 30
MIN_LINES, MAX_LINES = 3, 8


def build_clean_set(seed: int, plan: SetPlan) -> DocumentSet:
    rng = make_rng(seed, plan.index, "clean")
    set_id = f"set-{plan.index:03d}"

    entry = rng.choice(SUPPLIERS)
    buyer = rng.choice(BUYERS)
    n_lines = rng.randint(MIN_LINES, min(MAX_LINES, len(entry.products)))
    products = rng.sample(entry.products, n_lines)
    po_lines = tuple(_po_line(rng, no, product) for no, product in enumerate(products, start=1))

    delivered = {line.sku: line.quantity for line in po_lines}
    if plan.partial_delivery:
        short_line = rng.choice(po_lines)
        step = next(p.qty_step for p in products if p.sku == short_line.sku)
        steps_ordered = int(short_line.quantity / step)
        delivered[short_line.sku] = short_line.quantity - step * rng.randint(1, steps_ordered - 1)

    po_date = BASE_DATE + timedelta(days=rng.randint(0, 300))
    dn_date = po_date + timedelta(days=rng.randint(2, 10))
    invoice_date = dn_date + timedelta(days=rng.randint(0, 5))
    # The set index makes numbers unique across sets; the random suffix keeps them
    # from looking like a plain counter.
    suffix = f"{plan.index:03d}{rng.randint(0, 99):02d}"
    po_number = f"PO-{po_date.year}-{suffix}"
    dn_number = f"DN-{dn_date.year}-{suffix}"
    invoice_number = f"INV-{invoice_date.year}-{suffix}"

    purchase_order = PurchaseOrder(
        document_id=f"{set_id}-po",
        po_number=po_number,
        issue_date=po_date,
        buyer=buyer,
        supplier=entry.supplier,
        lines=po_lines,
        net_total=sum((line.line_net for line in po_lines), Decimal("0.00")),
    )
    delivery_note = DeliveryNote(
        document_id=f"{set_id}-dn",
        dn_number=dn_number,
        po_number=po_number,
        delivery_date=dn_date,
        buyer=buyer,
        supplier=entry.supplier,
        lines=tuple(
            DNLine(
                line_no=line.line_no,
                sku=line.sku,
                description=line.description,
                quantity_delivered=delivered[line.sku],
            )
            for line in po_lines
        ),
    )
    invoice_lines = tuple(
        _invoice_line(line.line_no, line, delivered[line.sku]) for line in po_lines
    )
    totals = invoice_totals(invoice_lines)
    invoice = Invoice(
        document_id=f"{set_id}-inv-1",
        invoice_number=invoice_number,
        po_number=po_number,
        delivery_note_numbers=(dn_number,),
        issue_date=invoice_date,
        due_date=invoice_date + timedelta(days=PAYMENT_TERMS_DAYS),
        buyer=buyer,
        supplier=entry.supplier,
        lines=invoice_lines,
        net_total=totals.net,
        vat_total=totals.vat,
        gross_total=totals.gross,
    )
    return DocumentSet(
        set_id=set_id,
        template=plan.template,
        purchase_order=purchase_order,
        delivery_note=delivery_note,
        invoices=(invoice,),
    )


def _po_line(rng: random.Random, line_no: int, product: Product) -> POLine:
    quantity = product.qty_step * rng.randint(product.qty_low, product.qty_high)
    unit_price = random_decimal(rng, product.price_low, product.price_high, product.price_places)
    return POLine(
        line_no=line_no,
        sku=product.sku,
        description=product.description,
        quantity=quantity,
        unit_price=unit_price,
        vat_rate=VAT_RATE,
        line_net=line_net(quantity, unit_price),
    )


def _invoice_line(line_no: int, po_line: POLine, quantity: Decimal) -> InvoiceLine:
    """Invoice what was delivered, at the price that was ordered."""
    net = line_net(quantity, po_line.unit_price)
    return InvoiceLine(
        line_no=line_no,
        sku=po_line.sku,
        description=po_line.description,
        quantity=quantity,
        unit_price=po_line.unit_price,
        vat_rate=po_line.vat_rate,
        line_net=net,
        line_vat=line_vat(net, po_line.vat_rate),
    )
