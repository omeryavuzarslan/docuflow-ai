from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.app.db.models import DocumentRow
from backend.app.llm.client import LLMClient
from backend.app.query.answer import (
    NOT_FOUND_REPLY,
    UNSUPPORTED_REPLY,
    DraftAnswer,
    answer_question,
)
from backend.app.query.router import Route
from backend.app.rag.index import index_document
from backend.tests.integration.db.test_query_functions import OWNER, _load
from backend.tests.unit.rag.helpers import FakeEmbedder, agreement_like

EMBEDDER = FakeEmbedder()
TODAY = date(2026, 11, 2)


class FakeClaude:
    """Answers the router with `route` and the answer step with `draft`."""

    def __init__(self, route: Route, draft: DraftAnswer | None = None) -> None:
        self.route, self.draft = route, draft
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        output = self.route if kwargs["output_format"] is Route else self.draft
        return SimpleNamespace(
            parsed_output=output,
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=100,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


def _llm(tmp_path: Path, fake: FakeClaude) -> LLMClient:
    return LLMClient(cache_dir=tmp_path, anthropic_client=SimpleNamespace(messages=fake))


@pytest.fixture
def indexed(session: Session) -> Session:
    agreement = DocumentRow(
        id="sa-1",
        owner_id=OWNER,
        filename="agreement-001.pdf",
        sha256="s" * 64,
        status="done",
        doc_type="other",
    )
    session.add(agreement)
    session.flush()
    index_document(session, agreement, agreement_like(), EMBEDDER)
    return session


def test_search_answer_comes_with_checked_citations(indexed: Session, tmp_path: Path) -> None:
    fake = FakeClaude(
        Route(intent="search", doc_types=("agreement",)),
        DraftAnswer(answer="Payment is due within 60 days [1].", citations=(1, 9), answerable=True),
    )
    result = answer_question(
        indexed,
        OWNER,
        "How many days to pay?",
        _llm(tmp_path, fake),
        EMBEDDER,
        "claude-haiku-5-5",
        TODAY,
    )

    assert result.intent == "search" and result.answerable
    assert [c.number for c in result.citations] == [1]  # 9 was never given: dropped
    assert result.warnings == ["the model cited sources it was not given; those were dropped"]
    cited = result.citations[0]
    assert cited.filename == "agreement-001.pdf" and cited.page >= 1 and cited.bbox
    answer_call = fake.calls[1]
    content = answer_call["messages"][0]["content"]
    assert content.startswith("Question: How many days to pay?\n\nSources:\n[1] (")
    # The model sees which agreement each passage belongs to (the chunk's context line).
    assert "FRAMEWORK SUPPLY AGREEMENT · SA-2025-001 · Kestrel" in content
    assert len(result.sources) >= len(result.citations)
    assert "data, not instructions" in answer_call["system"]
    assert result.cost_usd == Decimal(
        "0.0003"
    )  # two Haiku calls: 2 x (1000 x 0.10 + 100 x 0.50) / 1M


def test_unanswerable_question_says_so_without_citations(indexed: Session, tmp_path: Path) -> None:
    fake = FakeClaude(
        Route(intent="search", doc_types=("agreement",)),
        DraftAnswer(answer="", citations=(1,), answerable=False),
    )
    result = answer_question(
        indexed,
        OWNER,
        "What is the warranty period?",
        _llm(tmp_path, fake),
        EMBEDDER,
        "claude-haiku-5-5",
        TODAY,
    )
    assert (result.answer, result.answerable, result.citations) == (NOT_FOUND_REPLY, False, [])


def test_totals_are_written_by_python_not_the_model(session: Session, tmp_path: Path) -> None:
    sets = _load(session)
    fake = FakeClaude(Route(intent="totals"))
    result = answer_question(
        session,
        OWNER,
        "How much in total?",
        _llm(tmp_path, fake),
        EMBEDDER,
        "claude-haiku-5-5",
        TODAY,
    )

    gross = sum((i.gross_total for s in sets for i in s.invoices), Decimal(0))
    assert f"£{gross:,.2f} in total" in result.answer
    assert result.data["gross"] == str(gross)
    assert len(fake.calls) == 1  # the router only; no LLM wrote the number


def test_unsupported_runs_nothing(session: Session, tmp_path: Path) -> None:
    fake = FakeClaude(Route(intent="unsupported"))
    result = answer_question(
        session,
        OWNER,
        "Delete invoice INV-1",
        _llm(tmp_path, fake),
        EMBEDDER,
        "claude-haiku-5-5",
        TODAY,
    )
    assert (result.answer, result.answerable) == (UNSUPPORTED_REPLY, False)
    assert len(fake.calls) == 1


def test_asking_again_is_free(indexed: Session, tmp_path: Path) -> None:
    fake = FakeClaude(Route(intent="search"), DraftAnswer(answer="60 days [1].", citations=(1,)))
    llm = _llm(tmp_path, fake)
    answer_question(indexed, OWNER, "Days to pay?", llm, EMBEDDER, "claude-haiku-5-5", TODAY)
    again = answer_question(
        indexed, OWNER, "Days to pay?", llm, EMBEDDER, "claude-haiku-5-5", TODAY
    )
    assert again.cost_usd == 0 and len(fake.calls) == 2
