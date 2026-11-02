"""Generate one supplier agreement per (supplier, buyer) pair.

Terms come from a seeded RNG; the prose is built from the terms, with a few phrasings per
clause so that the same fact is not always worded the same way (otherwise keyword search
would look better than it is). Fifteen near-identical contracts that differ in their numbers
are also a deliberately hard test for retrieval: it has to find the right *contract*, not
just the right kind of clause.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from backend.app.domain.agreements import AgreementSection, PriceListItem, SupplierAgreement
from backend.app.domain.parties import Buyer
from data_generator.catalog import BUYERS, SUPPLIERS, SupplierEntry
from data_generator.render import format_money, format_price
from data_generator.rng import make_rng

BASE_DATE = date(2025, 1, 1)


def build_agreements(seed: int) -> tuple[SupplierAgreement, ...]:
    agreements = []
    for s, entry in enumerate(SUPPLIERS):
        for b, buyer in enumerate(BUYERS):
            index = 1 + s * len(BUYERS) + b
            agreements.append(
                _agreement(make_rng(seed, 1000 + index, "agreement"), index, entry, buyer)
            )
    return tuple(agreements)


def _pct(value: Decimal) -> str:
    return f"{value * 100:.0f}%"


def _agreement(
    rng: random.Random, index: int, entry: SupplierEntry, buyer: Buyer
) -> SupplierAgreement:
    effective_date = BASE_DATE + timedelta(days=rng.randint(0, 300))
    draft = SupplierAgreement(
        document_id=f"agreement-{index:03d}",
        agreement_number=f"SA-{effective_date.year}-{index:03d}",
        supplier=entry.supplier,
        buyer=buyer,
        effective_date=effective_date,
        term_months=rng.choice((12, 24, 36)),
        payment_terms_days=rng.choice((14, 30, 45, 60)),
        late_payment_interest=Decimal(rng.choice((4, 6, 8))) / 100,
        price_fixed_months=rng.choice((6, 12)),
        max_price_increase=Decimal(rng.choice((3, 4, 5, 6, 8))) / 100,
        price_review_notice_days=rng.choice((30, 60, 90)),
        minimum_order_value=Decimal(rng.choice((100, 150, 250, 500))),
        delivery_lead_days=rng.choice((2, 3, 5, 7, 10)),
        shortage_report_hours=rng.choice((24, 48, 72)),
        returns_window_days=rng.choice((14, 28, 30)),
        termination_notice_days=rng.choice((30, 60, 90)),
        price_list=tuple(
            PriceListItem(
                sku=p.sku,
                description=p.description,
                unit_price=Decimal(rng.randint(p.price_low, p.price_high)).scaleb(-p.price_places),
            )
            for p in entry.products
        ),
        sections=(AgreementSection(number=1, heading="-", text="-"),),  # replaced below
    )
    return draft.model_copy(update={"sections": _sections(draft, rng)})


def _sections(a: SupplierAgreement, rng: random.Random) -> tuple[AgreementSection, ...]:
    def pick(*options: str) -> str:
        return rng.choice(options)

    s, b = a.supplier.name, a.buyer.name
    texts = [
        (
            "Parties and term",
            f"This framework supply agreement {a.agreement_number} is made between {s} "
            f"(the Supplier, VAT {a.supplier.vat_number}) and {b} (the Buyer, VAT "
            f"{a.buyer.vat_number}). It takes effect on {a.effective_date:%d %B %Y} and "
            + pick(
                f"runs for {a.term_months} months.",
                f"continues for an initial term of {a.term_months} months.",
            )
            + " Individual purchases are made by purchase orders issued under this agreement.",
        ),
        (
            "Orders and delivery",
            pick(
                f"Each purchase order must have a value of at least "
                f"{format_money(a.minimum_order_value)} excluding VAT.",
                f"The Buyer will not place orders below {format_money(a.minimum_order_value)} "
                f"(net of VAT).",
            )
            + " "
            + pick(
                f"The Supplier shall deliver within {a.delivery_lead_days} working days of "
                f"receiving a purchase order.",
                f"Goods are to be delivered no later than {a.delivery_lead_days} working days "
                f"after the order is accepted.",
            )
            + " Partial deliveries are permitted; the balance is delivered as soon as available.",
        ),
        (
            "Prices and price review",
            "Prices are those in Schedule 1 and "
            + pick(
                f"are fixed for the first {a.price_fixed_months} months.",
                f"remain unchanged for {a.price_fixed_months} months from the effective date.",
            )
            + " "
            + pick(
                f"After that the Supplier may increase prices by no more than "
                f"{_pct(a.max_price_increase)} at any one review",
                f"Any later increase is capped at {_pct(a.max_price_increase)} per review",
            )
            + ", "
            + pick(
                f"giving at least {a.price_review_notice_days} days' written notice.",
                f"and requires {a.price_review_notice_days} days' notice in writing.",
            ),
        ),
        (
            "Invoicing and payment",
            "Each invoice must quote the purchase order number and the delivery note number. "
            + pick(
                f"The Buyer shall pay undisputed invoices within {a.payment_terms_days} days "
                f"of the invoice date.",
                f"Payment terms are {a.payment_terms_days} days from the date of invoice.",
            )
            + " "
            + pick(
                f"Late payments carry interest at {_pct(a.late_payment_interest)} a year "
                f"above the Bank of England base rate.",
                f"Interest on overdue sums runs at {_pct(a.late_payment_interest)} per annum "
                f"over base rate.",
            )
            + " The Buyer may withhold payment of any amount it disputes in good faith.",
        ),
        (
            "Shortages, damage and returns",
            pick(
                f"The Buyer shall report any shortage or damage within "
                f"{a.shortage_report_hours} hours of delivery.",
                f"Shortages and damaged goods must be notified to the Supplier within "
                f"{a.shortage_report_hours} hours.",
            )
            + " "
            + pick(
                f"Unused goods in original packaging may be returned within "
                f"{a.returns_window_days} days for a full credit.",
                f"Returns are accepted for {a.returns_window_days} days if the goods are "
                f"unused and in their original packaging.",
            ),
        ),
        (
            "Termination",
            pick(
                f"Either party may end this agreement by giving {a.termination_notice_days} "
                f"days' written notice.",
                f"This agreement may be terminated by either party on "
                f"{a.termination_notice_days} days' notice in writing.",
            )
            + " Orders placed before termination remain binding.",
        ),
        (
            "Governing law",
            "This agreement is governed by the law of England and Wales.",
        ),
    ]
    schedule = (
        "Agreed unit prices, excluding VAT: "
        + "; ".join(
            f"{item.sku} {item.description}: {format_price(item.unit_price)}"
            for item in a.price_list
        )
        + "."
    )
    texts.append(("Schedule 1: Price list", schedule))
    return tuple(
        AgreementSection(number=n, heading=heading, text=text)
        for n, (heading, text) in enumerate(texts, start=1)
    )
