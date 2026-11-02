"""The processing pipeline end to end against Postgres, with a fake parser and a fake LLM:
no Docling, no API calls, no cost."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.models import DiscrepancyRow, DocumentRow, ExtractionRow, InvoiceRow, JobRow
from backend.app.pipeline.process import ingest_file, process_document
from backend.app.worker import run_until_empty
from backend.tests.integration.db.fakes import OWNER, FakeWorld, fake_pdf
from data_generator.generate import generate


@pytest.fixture
def world(tmp_path: Path) -> FakeWorld:
    return FakeWorld(list(generate(42, 8)), tmp_path)


def _ingest_all(session: Session, world: FakeWorld, owner: str = OWNER) -> dict[str, str]:
    """Upload every generated document; returns {truth id: database id}."""
    ids = {}
    for truth_id in world.truth:
        row, _ = ingest_file(
            session, owner, f"{truth_id}.pdf", fake_pdf(truth_id), world.services.storage_root
        )
        ids[truth_id] = row.id
    session.commit()
    return ids


def _expected(world: FakeWorld, ids: dict[str, str]) -> list[tuple[str, str]]:
    sets = generate(42, 8)
    return sorted((ids[e.document_id], e.type.value) for s in sets for e in s.errors)


def _found(session: Session, owner: str = OWNER) -> list[tuple[str, str]]:
    rows = session.scalars(select(DiscrepancyRow).where(DiscrepancyRow.owner_id == owner))
    return sorted((r.document_id, r.type) for r in rows)


def test_ingest_stores_the_file_and_queues_one_job(session: Session, world: FakeWorld) -> None:
    row, job = ingest_file(
        session, OWNER, "a.pdf", fake_pdf("set-001-po"), world.services.storage_root
    )
    assert row.status == "queued"
    assert Path(row.storage_path or "").read_bytes() == fake_pdf("set-001-po")
    assert job is not None and job.payload == {"document_id": row.id}


def test_uploading_the_same_file_again_does_nothing_new(session: Session, world: FakeWorld) -> None:
    first, _ = ingest_file(
        session, OWNER, "a.pdf", fake_pdf("set-001-po"), world.services.storage_root
    )
    again, job = ingest_file(
        session, OWNER, "copy.pdf", fake_pdf("set-001-po"), world.services.storage_root
    )
    assert again.id == first.id
    assert job is None
    assert len(session.scalars(select(JobRow)).all()) == 1


def test_worker_processes_everything_and_finds_exactly_the_injected_errors(
    session_factory: sessionmaker[Session], world: FakeWorld
) -> None:
    with session_factory() as session:
        ids = _ingest_all(session, world)

    processed = run_until_empty(session_factory, world.services, worker_id="test")

    with session_factory() as session:
        assert processed == len(ids)
        statuses = session.scalars(
            select(DocumentRow.status).where(DocumentRow.owner_id == OWNER)
        ).all()
        assert set(statuses) == {"done"}
        assert set(session.scalars(select(JobRow.status)).all()) == {"done"}
        assert _found(session) == _expected(world, ids)


def test_unreadable_document_goes_to_review_without_knock_on_alarms(
    session: Session, world: FakeWorld
) -> None:
    world.broken.add("set-002-po")  # its supplier cannot be read
    ids = _ingest_all(session, world)
    for db_id in ids.values():
        process_document(session, db_id, OWNER, world.services)

    po = session.get(DocumentRow, ids["set-002-po"])
    assert po is not None and po.status == "needs_review"
    # The PO's delivery note and invoice are not flagged as "no matching PO".
    assert "unmatched_document" not in {t for _, t in _found(session)}
    assert _found(session) == _expected(world, ids)


def test_reprocessing_adds_a_new_extraction_version_and_keeps_the_old(
    session: Session, world: FakeWorld
) -> None:
    row, _ = ingest_file(
        session, OWNER, "inv.pdf", fake_pdf("set-003-inv-1"), world.services.storage_root
    )
    process_document(session, row.id, OWNER, world.services)
    process_document(session, row.id, OWNER, world.services)

    versions = session.scalars(
        select(ExtractionRow.version)
        .where(ExtractionRow.document_id == row.id)
        .order_by(ExtractionRow.version)
    ).all()
    assert versions == [1, 2]
    # Same file, prompt and model: the second answer comes from the cache and costs nothing.
    cached = session.scalars(
        select(ExtractionRow.cached)
        .where(ExtractionRow.document_id == row.id)
        .order_by(ExtractionRow.version)
    ).all()
    assert cached == [False, True]
    assert session.get(InvoiceRow, row.id) is not None  # typed row replaced, not duplicated


def test_a_dismissed_finding_stays_dismissed_after_revalidation(
    session: Session, world: FakeWorld
) -> None:
    ids = _ingest_all(session, world)
    for db_id in ids.values():
        process_document(session, db_id, OWNER, world.services)
    finding = session.scalars(select(DiscrepancyRow)).first()
    assert finding is not None
    finding.status = "dismissed"
    session.flush()

    process_document(session, ids["set-001-po"], OWNER, world.services)  # triggers revalidation

    rows = session.scalars(
        select(DiscrepancyRow).where(
            DiscrepancyRow.document_id == finding.document_id, DiscrepancyRow.rule == finding.rule
        )
    ).all()
    assert [r.status for r in rows] == ["dismissed"]


def test_owners_never_see_each_others_documents(session: Session, world: FakeWorld) -> None:
    ids_a = _ingest_all(session, world, owner="owner-a")
    # Owner B only has the invoices: without A's orders they must all be unmatched.
    ids_b = {}
    for truth_id in world.truth:
        if "-inv-" in truth_id:
            row, _ = ingest_file(
                session,
                "owner-b",
                f"{truth_id}.pdf",
                fake_pdf(truth_id),
                world.services.storage_root,
            )
            ids_b[truth_id] = row.id
    for db_id in ids_a.values():
        process_document(session, db_id, "owner-a", world.services)
    for db_id in ids_b.values():
        process_document(session, db_id, "owner-b", world.services)

    assert _found(session, "owner-a") == _expected(world, ids_a)
    types_b = {t for _, t in _found(session, "owner-b")}
    assert "unmatched_document" in types_b
    with pytest.raises(PermissionError):
        process_document(session, ids_a["set-001-po"], "owner-b", world.services)
