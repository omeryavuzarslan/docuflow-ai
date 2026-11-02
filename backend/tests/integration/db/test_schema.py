from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.mapping import (
    ROW_CLASSES,
    Document,
    DocumentRowType,
    document_from_row,
    document_to_row,
)
from backend.app.db.models import (
    Base,
    CorrectionRow,
    DocumentRow,
    ExtractionRow,
    InvoiceRow,
)
from backend.app.domain.document_set import DocumentSet
from data_generator.generate import generate

OWNER = "owner-a"


def _documents(doc_set: DocumentSet) -> list[Document]:
    return [doc_set.purchase_order, doc_set.delivery_note, *doc_set.invoices]


def test_migrations_create_exactly_the_tables_the_models_describe(engine: Engine) -> None:
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def _store(
    session: Session, document_id: str, sha: str = "0" * 64, owner: str = OWNER
) -> DocumentRow:
    row = DocumentRow(
        id=document_id,
        owner_id=owner,
        filename=f"{document_id}.pdf",
        sha256=sha,
        status="done",
    )
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize("seed", range(10))
def test_every_document_type_round_trips_exactly(session: Session, seed: int) -> None:
    # Domain model -> tables -> domain model gives back the identical document: the two
    # representations cannot drift apart without this test failing.
    for doc_set in generate(seed, 8):
        for document in _documents(doc_set):
            _store(session, document.document_id, sha=f"{seed}-{document.document_id}")
            session.add(document_to_row(document, owner_id=OWNER))
    session.flush()
    session.expunge_all()  # force reading back from the database, not the identity map

    for doc_set in generate(seed, 8):
        for document in _documents(doc_set):
            row = session.get(ROW_CLASSES[document.doc_type], document.document_id)
            assert isinstance(row, DocumentRowType)
            assert document_from_row(row) == document


def test_money_keeps_exact_decimal_values(session: Session) -> None:
    invoice = generate(1, 8)[0].invoices[0]
    _store(session, invoice.document_id)
    session.add(document_to_row(invoice, OWNER))
    session.flush()
    session.expunge_all()
    row = session.get(InvoiceRow, invoice.document_id)
    assert row is not None
    assert isinstance(row.gross_total, Decimal)
    assert row.gross_total == invoice.gross_total
    assert row.lines[0].unit_price == invoice.lines[0].unit_price


def test_same_file_twice_for_one_owner_is_rejected(session: Session) -> None:
    _store(session, "doc-1", sha="a" * 64)
    with pytest.raises(IntegrityError):
        _store(session, "doc-2", sha="a" * 64)


def test_two_owners_may_upload_the_same_file(session: Session) -> None:
    _store(session, "doc-1", sha="a" * 64, owner="owner-a")
    _store(session, "doc-2", sha="a" * 64, owner="owner-b")
    owners = session.scalars(select(DocumentRow.owner_id).order_by(DocumentRow.owner_id)).all()
    assert owners == ["owner-a", "owner-b"]


def test_corrections_never_change_the_raw_extraction(session: Session) -> None:
    _store(session, "doc-1")
    raw = {"doc_type": "invoice", "buyer": {"name": "Harbour & Hale Retail ple"}}
    extraction = ExtractionRow(
        document_id="doc-1",
        owner_id=OWNER,
        version=1,
        model="claude-haiku-5-5",
        prompt_version="extract-v2",
        raw=raw,
        conversion_errors=[],
        provenance={},
        input_tokens=3000,
        output_tokens=600,
        cost_usd=Decimal("0.0006"),
    )
    session.add(extraction)
    session.flush()
    session.add(
        CorrectionRow(
            document_id="doc-1",
            owner_id=OWNER,
            extraction_id=extraction.id,
            field="buyer.name",
            old_value="Harbour & Hale Retail ple",
            new_value="Harbour & Hale Retail plc",
            author="reviewer@example.com",
        )
    )
    session.flush()
    session.expunge_all()

    stored = session.scalars(select(ExtractionRow)).one()
    assert stored.raw == raw
    assert stored.cost_usd == Decimal("0.0006")
    assert session.scalars(select(CorrectionRow.new_value)).one() == "Harbour & Hale Retail plc"


def test_extraction_versions_are_unique_per_document(session: Session) -> None:
    _store(session, "doc-1")
    common = {
        "document_id": "doc-1",
        "owner_id": OWNER,
        "model": "m",
        "prompt_version": "p",
        "raw": {},
        "conversion_errors": [],
        "provenance": {},
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": Decimal(0),
    }
    session.add(ExtractionRow(version=1, **common))
    session.flush()
    with pytest.raises(IntegrityError):
        session.add(ExtractionRow(version=1, **common))
        session.flush()
