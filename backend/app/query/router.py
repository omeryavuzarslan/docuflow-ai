"""Question -> route -> answer data.

The router is one cheap LLM call (Haiku) with structured output: it picks an intent and its
parameters. Python then validates them and calls a fixed function: SQL for numbers, the
findings table, document lookup, or hybrid retrieval restricted to the right document types.
The LLM never writes SQL and never computes a number.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from backend.app.llm.client import CacheKey, LLMClient, LLMUsage
from backend.app.llm.prompts import load_prompt
from backend.app.llm.schema import LLMOutput
from backend.app.query.functions import (
    FindingSummary,
    FoundDocument,
    InvoiceTotals,
    find_documents,
    invoice_totals,
    list_findings,
)
from backend.app.rag.embeddings import Embedder
from backend.app.rag.retrieve import Hit, hybrid_search

ROUTE_PROMPT_VERSION = "route-v1"

Intent = Literal["totals", "document_lookup", "findings", "search", "unsupported"]
DocTypeName = Literal["agreement", "invoice", "purchase_order", "delivery_note"]
# Agreements are stored with the extraction's catch-all type.
_STORED_TYPE = {
    "agreement": "other",
    "invoice": "invoice",
    "purchase_order": "purchase_order",
    "delivery_note": "delivery_note",
}


class Route(LLMOutput):
    intent: Intent
    supplier: str = ""
    buyer: str = ""
    date_from: str = ""
    date_to: str = ""
    document_number: str = ""
    doc_types: tuple[DocTypeName, ...] = ()
    finding_status: Literal["open", "resolved", "dismissed", "any"] = "open"


@dataclass(frozen=True)
class Routed:
    route: Route
    usage: LLMUsage
    cached: bool


@dataclass(frozen=True)
class RouteResult:
    intent: Intent
    route: Route
    totals: InvoiceTotals | None = None
    documents: list[FoundDocument] = field(default_factory=list)
    findings: list[FindingSummary] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # parameters that had to be dropped


def route_question(llm: LLMClient, question: str, today: date, model: str) -> Routed:
    user = f"Today: {today.isoformat()}\nQuestion: {question}"
    result = llm.parse(
        model=model,
        system=load_prompt(ROUTE_PROMPT_VERSION),
        user=user,
        output_format=Route,
        cache_key=CacheKey(
            file_sha256=hashlib.sha256(b"router").hexdigest(),
            input_sha256=hashlib.sha256(user.encode()).hexdigest(),
            prompt_version=ROUTE_PROMPT_VERSION,
            model=model,
        ),
    )
    return Routed(route=result.output, usage=result.usage, cached=result.cached)


def _date(text: str, name: str, problems: list[str]) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        problems.append(f"{name}: not a date ({text!r}), ignored")
        return None


def dispatch(
    session: Session,
    owner_id: str,
    route: Route,
    question: str,
    embedder: Embedder,
    k: int = 5,
) -> RouteResult:
    problems: list[str] = []
    if route.intent == "totals":
        totals = invoice_totals(
            session,
            owner_id,
            supplier=route.supplier or None,
            buyer=route.buyer or None,
            date_from=_date(route.date_from, "date_from", problems),
            date_to=_date(route.date_to, "date_to", problems),
        )
        return RouteResult("totals", route, totals=totals, problems=problems)
    if route.intent == "document_lookup":
        if not route.document_number.strip():
            problems.append("document_number missing")
            return RouteResult("document_lookup", route, problems=problems)
        documents = find_documents(session, owner_id, route.document_number)
        return RouteResult("document_lookup", route, documents=documents)
    if route.intent == "findings":
        findings = list_findings(session, owner_id, route.finding_status, route.supplier or None)
        return RouteResult("findings", route, findings=findings)
    if route.intent == "search":
        types = sorted({_STORED_TYPE[t] for t in route.doc_types}) or None
        hits = hybrid_search(session, owner_id, question, embedder, k=k, doc_types=types)
        return RouteResult("search", route, hits=hits)
    return RouteResult("unsupported", route)
