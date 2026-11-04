"""Question -> answer with citations.

route -> dispatch -> answer:
- totals, document lookup, findings: the answer sentence is written by Python from the
  query result. Numbers never pass through the LLM.
- search: the top passages are numbered and given to the LLM, which answers from them only
  and says which numbers it used. Python checks that every cited number was actually given
  and returns each citation with its file, page and box, so the UI can show the passage.
- unsupported: a fixed reply; nothing is run.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import Field
from sqlalchemy.orm import Session

from backend.app.llm.client import CacheKey, LLMClient
from backend.app.llm.prompts import load_prompt
from backend.app.llm.schema import LLMOutput
from backend.app.query.router import RouteResult, dispatch, route_question
from backend.app.rag.embeddings import Embedder
from backend.app.rag.retrieve import Hit

ANSWER_PROMPT_VERSION = "answer-v1"
TOP_K = 5

UNSUPPORTED_REPLY = (
    "I can answer questions about your invoices, purchase orders, delivery notes and supplier "
    "agreements, but I can't do that. I don't change, delete, approve or send anything."
)
NOT_FOUND_REPLY = "The documents provided do not state this."


class DraftAnswer(LLMOutput):
    answer: str
    citations: tuple[int, ...] = Field(default=(), description="Numbers of the sources used.")
    answerable: bool = True


@dataclass(frozen=True)
class Citation:
    number: int  # as shown to the model, 1-based
    document_id: str
    filename: str
    heading: str
    page: int
    bbox: dict[str, Any]
    text: str


@dataclass(frozen=True)
class AskResult:
    question: str
    intent: str
    answer: str
    answerable: bool
    citations: list[Citation] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)  # structured result for the UI
    sources: list[Citation] = field(default_factory=list)  # every passage the model saw
    cost_usd: Decimal = Decimal(0)  # new spending for this question (cache hits are free)
    warnings: list[str] = field(default_factory=list)


def _money(value: Decimal) -> str:
    return f"£{value:,.2f}"


def sources_block(hits: list[Hit]) -> str:
    """Numbered passages for the model. Each carries its chunk's context line (which
    agreement or document, between whom), not just the passage: fifteen price lists look
    the same, and without it the model cannot tell whose prices it is reading."""
    parts = []
    for n, hit in enumerate(hits, start=1):
        parts.append(f"[{n}] ({hit.filename}, page {hit.page})\n{hit.text}")
    return "\n\n".join(parts)


def _structured_answer(result: RouteResult) -> tuple[str, dict[str, Any]]:
    """Answers whose facts come from SQL: written here, deterministically."""
    if result.intent == "totals" and result.totals is not None:
        t = result.totals
        who = f" from {', '.join(t.suppliers)}" if result.route.supplier and t.suppliers else ""
        period = ""
        if result.route.date_from or result.route.date_to:
            period = f" dated {result.route.date_from or '…'} to {result.route.date_to or '…'}"
        if t.count == 0:
            return f"No invoices{who}{period} were found.", {"count": 0}
        text = (
            f"{t.count} invoice{'s' if t.count != 1 else ''}{who}{period}: "
            f"{_money(t.gross)} in total ({_money(t.net)} net + {_money(t.vat)} VAT)."
        )
        data = {"count": t.count, "net": str(t.net), "vat": str(t.vat), "gross": str(t.gross)}
        return text, data
    if result.intent == "document_lookup":
        if not result.documents:
            return f"No document numbered {result.route.document_number} was found.", {}
        listed = "; ".join(
            f"{d.doc_type.replace('_', ' ')} {d.number} ({d.filename}, {d.status})"
            for d in result.documents
        )
        return f"Found: {listed}.", {"documents": [d.document_id for d in result.documents]}
    if result.intent == "findings":
        if not result.findings:
            return "No matching findings.", {"count": 0}
        lines = [f"{f.filename}: {f.message}" for f in result.findings[:10]]
        more = f" (and {len(result.findings) - 10} more)" if len(result.findings) > 10 else ""
        text = f"{len(result.findings)} finding(s){more}: " + " | ".join(lines)
        return text, {"findings": [f.discrepancy_id for f in result.findings]}
    return UNSUPPORTED_REPLY, {}


def answer_question(
    session: Session,
    owner_id: str,
    question: str,
    llm: LLMClient,
    embedder: Embedder,
    model: str,
    today: date,
) -> AskResult:
    routed = route_question(llm, question, today, model)
    cost = Decimal(0) if routed.cached else routed.usage.cost_usd
    result = dispatch(session, owner_id, routed.route, question, embedder, k=TOP_K)

    if result.intent != "search":
        text, data = _structured_answer(result)
        return AskResult(
            question=question,
            intent=result.intent,
            answer=text,
            answerable=result.intent != "unsupported",
            data=data,
            cost_usd=cost,
            warnings=result.problems,
        )

    if not result.hits:
        return AskResult(question, "search", NOT_FOUND_REPLY, False, cost_usd=cost)

    user = f"Question: {question}\n\nSources:\n{sources_block(result.hits)}"
    drafted = llm.parse(
        model=model,
        system=load_prompt(ANSWER_PROMPT_VERSION),
        user=user,
        output_format=DraftAnswer,
        cache_key=CacheKey(
            file_sha256=hashlib.sha256(b"answer").hexdigest(),
            input_sha256=hashlib.sha256(user.encode()).hexdigest(),
            prompt_version=ANSWER_PROMPT_VERSION,
            model=model,
        ),
    )
    if not drafted.cached:
        cost += drafted.usage.cost_usd
    draft = drafted.output

    warnings: list[str] = []
    valid = sorted({n for n in draft.citations if 1 <= n <= len(result.hits)})
    if len(valid) != len(set(draft.citations)):
        warnings.append("the model cited sources it was not given; those were dropped")
    if draft.answerable and not valid:
        warnings.append("the answer cites no source")
    sources = [
        Citation(
            number=n,
            document_id=hit.document_id,
            filename=hit.filename,
            heading=hit.heading,
            page=hit.page,
            bbox=hit.bbox,
            text=hit.text,
        )
        for n, hit in enumerate(result.hits, start=1)
    ]
    citations = [sources[n - 1] for n in valid]
    return AskResult(
        question=question,
        intent="search",
        answer=draft.answer if draft.answerable else (draft.answer or NOT_FOUND_REPLY),
        answerable=draft.answerable and bool(citations),
        citations=citations if draft.answerable else [],
        sources=sources,
        cost_usd=cost,
        warnings=warnings,
    )
