from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import ChunkRow, DocumentRow
from backend.app.rag.index import index_document
from backend.app.rag.retrieve import search
from backend.tests.unit.rag.helpers import FakeEmbedder, agreement_like

EMBEDDER = FakeEmbedder()


def _document(session: Session, owner: str, document_id: str) -> DocumentRow:
    row = DocumentRow(
        id=document_id,
        owner_id=owner,
        filename=f"{document_id}.pdf",
        sha256=document_id.ljust(64, "0"),
        status="done",
    )
    session.add(row)
    session.flush()
    return row


def test_search_finds_the_matching_chunk_with_its_location(session: Session) -> None:
    document = _document(session, "owner-a", "agreement-001")
    index_document(session, document, agreement_like(), EMBEDDER)

    hits = search(session, "owner-a", "how many days for payment of the invoice", EMBEDDER, k=3)

    assert hits[0].heading == "4. Invoicing and payment"
    assert hits[0].document_id == "agreement-001"
    assert hits[0].filename == "agreement-001.pdf"
    assert hits[0].page == 1
    assert 0 < hits[0].score <= 1
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_search_never_returns_another_owners_chunks(session: Session) -> None:
    index_document(session, _document(session, "owner-a", "a-doc"), agreement_like(), EMBEDDER)
    index_document(session, _document(session, "owner-b", "b-doc"), agreement_like(), EMBEDDER)

    hits = search(session, "owner-b", "payment terms invoice", EMBEDDER, k=50)

    assert hits and {h.document_id for h in hits} == {"b-doc"}


def test_reindexing_replaces_the_chunks(session: Session) -> None:
    document = _document(session, "owner-a", "agreement-001")
    index_document(session, document, agreement_like(), EMBEDDER)
    first = session.scalar(select(func.count()).select_from(ChunkRow))
    index_document(session, document, agreement_like(), EMBEDDER)
    assert session.scalar(select(func.count()).select_from(ChunkRow)) == first


def test_fixed_strategy_can_be_indexed_for_comparison(session: Session) -> None:
    document = _document(session, "owner-a", "agreement-001")
    index_document(session, document, agreement_like(), EMBEDDER, strategy="fixed")
    kinds = set(session.scalars(select(ChunkRow.kind)))
    assert kinds == {"fixed"}
