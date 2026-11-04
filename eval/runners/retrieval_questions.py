"""The retrieval test set: questions about the generated supplier agreements, each with the
document and evidence that answer it. Built from the agreements' typed terms, before and
independently of any retrieval code, so the test does not adapt to the system.

A retrieved chunk counts as relevant when it comes from the right agreement and contains
every evidence string. Evidence is a short span around the fact (at most ~70 characters),
so a fixed-size window with 100 characters of overlap can always contain it in full: the
comparison between chunking strategies stays fair.
"""

import random
from dataclasses import dataclass
from decimal import Decimal

from backend.app.domain.agreements import SupplierAgreement
from backend.app.domain.document_set import DocumentSet
from data_generator.render import format_date, format_money, format_price

QUESTIONS_PER_AGREEMENT = 8
_SPAN = 30  # characters of context kept on each side of the fact


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    question: str
    document_id: str
    evidence: tuple[str, ...]
    doc_type: str = "other"  # type of the answering document (agreements are "other")
    fact: str = ""  # the answer as printed, e.g. "60 days" (used by the answer eval)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _span(text: str, fact: str) -> str:
    """The fact with up to _SPAN characters either side, cut at word boundaries."""
    text = _norm(text)
    i = text.index(fact)
    start = max(0, i - _SPAN)
    end = min(len(text), i + len(fact) + _SPAN)
    if start > 0:
        start = text.index(" ", start) + 1
    if end < len(text):
        end = text.rindex(" ", 0, end)
    return text[start:end]


def _section(a: SupplierAgreement, heading: str) -> str:
    return next(s.text for s in a.sections if s.heading == heading)


def _pct(value: Decimal) -> str:
    return f"{value * 100:.0f}%"


def _candidates(a: SupplierAgreement) -> list[tuple[str, str, str, str]]:
    """(kind, question, section heading, fact as printed)."""
    s, b = a.supplier.name, a.buyer.name
    item = a.price_list[len(a.price_list) // 2]
    return [
        (
            "payment_terms",
            f"How many days does {b} have to pay invoices from {s}?",
            "Invoicing and payment",
            f"{a.payment_terms_days} days",
        ),
        (
            "late_interest",
            f"What interest can {s} charge {b} on late payments?",
            "Invoicing and payment",
            _pct(a.late_payment_interest),
        ),
        (
            "price_cap",
            f"By how much may {s} raise its prices to {b} at a review?",
            "Prices and price review",
            _pct(a.max_price_increase),
        ),
        (
            "price_notice",
            f"How much notice must {s} give {b} before increasing prices?",
            "Prices and price review",
            f"{a.price_review_notice_days} days",
        ),
        (
            "price_fixed",
            f"For how long are {s}'s prices to {b} fixed?",
            "Prices and price review",
            f"{a.price_fixed_months} months",
        ),
        (
            "lead_time",
            f"How quickly does {s} have to deliver an order placed by {b}?",
            "Orders and delivery",
            f"{a.delivery_lead_days} working days",
        ),
        (
            "minimum_order",
            f"What is the smallest order {b} may place with {s}?",
            "Orders and delivery",
            f"£{a.minimum_order_value:,.2f}",
        ),
        (
            "shortage_window",
            f"How soon must {b} tell {s} about missing or damaged goods?",
            "Shortages, damage and returns",
            f"{a.shortage_report_hours} hours",
        ),
        (
            "returns_window",
            f"Until when can {b} send unused goods back to {s}?",
            "Shortages, damage and returns",
            f"{a.returns_window_days} days",
        ),
        (
            "termination",
            f"How much notice ends the agreement between {s} and {b}?",
            "Termination",
            f"{a.termination_notice_days} days",
        ),
        (
            "price_list",
            f"What unit price did {b} agree with {s} for {item.description}?",
            "Schedule 1: Price list",
            item.sku,
        ),
    ]


def build_questions(agreements: tuple[SupplierAgreement, ...], seed: int) -> list[Question]:
    rng = random.Random(f"{seed}:retrieval-questions")
    questions: list[Question] = []
    for a in agreements:
        for kind, text, heading, fact in rng.sample(_candidates(a), QUESTIONS_PER_AGREEMENT):
            if kind == "price_list":
                item = next(i for i in a.price_list if i.sku == fact)
                evidence: tuple[str, ...] = (item.sku, format_price(item.unit_price))
                answer = format_price(item.unit_price)
            else:
                evidence = (_span(_section(a, heading), fact),)
                answer = fact
            questions.append(
                Question(
                    id=f"{a.document_id}:{kind}",
                    kind=kind,
                    question=text,
                    document_id=a.document_id,
                    evidence=evidence,
                    fact=answer,
                )
            )
    return questions


def build_lookup_questions(
    agreements: tuple[SupplierAgreement, ...], sets: list[DocumentSet], seed: int
) -> list[Question]:
    """Questions that name an exact code: a SKU, an invoice number, a PO number. These are
    where keyword search should help dense retrieval most."""
    rng = random.Random(f"{seed}:lookup-questions")
    questions: list[Question] = []
    for a in agreements:
        item = rng.choice(a.price_list)
        questions.append(
            Question(
                id=f"{a.document_id}:sku_price",
                kind="sku_price",
                question=(
                    f"What is the agreed unit price for item {item.sku} between "
                    f"{a.buyer.name} and {a.supplier.name}?"
                ),
                document_id=a.document_id,
                evidence=(item.sku, format_price(item.unit_price)),
                fact=format_price(item.unit_price),
            )
        )
    for doc_set in sets:
        invoice = doc_set.invoices[0]  # a duplicate shares its number, so it is skipped
        questions.append(
            Question(
                id=f"{invoice.document_id}:invoice_total",
                kind="invoice_total",
                question=f"What is the total amount due on invoice {invoice.invoice_number}?",
                document_id=invoice.document_id,
                evidence=(format_money(invoice.gross_total),),
                doc_type="invoice",
            )
        )
        po = doc_set.purchase_order
        questions.append(
            Question(
                id=f"{po.document_id}:po_date",
                kind="po_date",
                question=f"On what date was purchase order {po.po_number} issued?",
                document_id=po.document_id,
                evidence=(format_date(po.issue_date),),
                doc_type="purchase_order",
            )
        )
    return questions


def is_relevant(question: Question, document_id: str, body: str) -> bool:
    text = _norm(body)
    return document_id == question.document_id and all(_norm(e) in text for e in question.evidence)


def first_relevant_rank(question: Question, hits: list[tuple[str, str]]) -> int | None:
    """1-based rank of the first relevant (document_id, body) hit, or None."""
    for rank, (document_id, body) in enumerate(hits, start=1):
        if is_relevant(question, document_id, body):
            return rank
    return None


def recall_at(ranks: list[int | None], k: int) -> float:
    return sum(r is not None and r <= k for r in ranks) / len(ranks)


def mean_reciprocal_rank(ranks: list[int | None]) -> float:
    return sum(1 / r for r in ranks if r is not None) / len(ranks)
