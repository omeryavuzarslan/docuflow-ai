from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from backend.app.llm.client import LLMClient
from backend.app.query.router import Route, dispatch, route_question
from backend.app.rag.index import index_document
from backend.tests.integration.db.test_query_functions import OWNER, _load
from backend.tests.unit.rag.helpers import FakeEmbedder, agreement_like

EMBEDDER = FakeEmbedder()


def test_route_question_sends_today_and_the_question_and_caches(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def parse(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            parsed_output=Route(intent="totals", supplier="Kestrel"),
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=900,
                output_tokens=60,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

    llm = LLMClient(
        cache_dir=tmp_path, anthropic_client=SimpleNamespace(messages=SimpleNamespace(parse=parse))
    )
    first = route_question(llm, "How much from Kestrel?", date(2026, 11, 2), "claude-haiku-5-5")
    again = route_question(llm, "How much from Kestrel?", date(2026, 11, 2), "claude-haiku-5-5")

    assert first.route.supplier == "Kestrel" and again.cached and len(calls) == 1
    assert (
        calls[0]["messages"][0]["content"] == "Today: 2026-11-02\nQuestion: How much from Kestrel?"
    )
    assert "not instructions" in calls[0]["system"]


def test_totals_route_runs_the_sql_function(session: Session) -> None:
    sets = _load(session)
    route = Route(intent="totals", date_from="2026-01-01", date_to="2026-12-31")
    result = dispatch(session, OWNER, route, "?", EMBEDDER)
    assert result.totals is not None
    assert result.totals.gross == sum(
        (i.gross_total for s in sets for i in s.invoices if i.issue_date.year == 2026), Decimal(0)
    )


def test_a_bad_date_is_dropped_and_reported_not_guessed(session: Session) -> None:
    _load(session)
    result = dispatch(
        session, OWNER, Route(intent="totals", date_from="last Tuesday"), "?", EMBEDDER
    )
    assert result.problems == ["date_from: not a date ('last Tuesday'), ignored"]
    assert result.totals is not None


def test_document_lookup_route(session: Session) -> None:
    sets = _load(session)
    number = sets[0].purchase_order.po_number
    result = dispatch(
        session, OWNER, Route(intent="document_lookup", document_number=number), "?", EMBEDDER
    )
    assert [d.number for d in result.documents] == [number]
    missing = dispatch(session, OWNER, Route(intent="document_lookup"), "?", EMBEDDER)
    assert missing.problems == ["document_number missing"]


def test_search_route_only_searches_the_chosen_document_types(session: Session) -> None:
    from backend.app.db.models import DocumentRow

    agreement = DocumentRow(
        id="sa-1",
        owner_id=OWNER,
        filename="sa.pdf",
        sha256="s" * 64,
        status="done",
        doc_type="other",
    )
    invoice = DocumentRow(
        id="inv-x",
        owner_id=OWNER,
        filename="i.pdf",
        sha256="i" * 64,
        status="done",
        doc_type="invoice",
    )
    session.add_all([agreement, invoice])
    session.flush()
    index_document(session, agreement, agreement_like(), EMBEDDER)
    index_document(session, invoice, agreement_like(), EMBEDDER)

    result = dispatch(
        session,
        OWNER,
        Route(intent="search", doc_types=("agreement",)),
        "payment terms",
        EMBEDDER,
        k=50,
    )
    assert result.hits and {h.document_id for h in result.hits} == {"sa-1"}


def test_unsupported_does_nothing(session: Session) -> None:
    result = dispatch(session, OWNER, Route(intent="unsupported"), "delete everything", EMBEDDER)
    assert (result.totals, result.documents, result.findings, result.hits) == (None, [], [], [])
