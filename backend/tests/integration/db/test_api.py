"""The HTTP API end to end: real Postgres (rolled back), fake parser and LLM, no cost."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.main import create_app
from backend.app.worker import run_until_empty
from backend.tests.integration.db.fakes import OWNER, FakeWorld, fake_pdf
from data_generator.generate import generate

A = {"X-Owner-Id": OWNER}
B = {"X-Owner-Id": "owner-b"}


@pytest.fixture
def world(tmp_path):  # type: ignore[no-untyped-def]
    return FakeWorld(list(generate(42, 8)), tmp_path)


@pytest.fixture
def client(session_factory: sessionmaker[Session], world: FakeWorld) -> Iterator[TestClient]:
    app = create_app(session_factory=session_factory, storage_root=world.root)
    with TestClient(app) as client:
        yield client


def _upload(client: TestClient, truth_id: str, headers: dict[str, str] = A) -> dict:  # type: ignore[type-arg]
    response = client.post(
        "/documents",
        headers=headers,
        files={"file": (f"{truth_id}.pdf", fake_pdf(truth_id), "application/pdf")},
    )
    assert response.status_code in (200, 202), response.text
    return response.json()  # type: ignore[no-any-return]


def _upload_all_and_process(
    client: TestClient, world: FakeWorld, session_factory: sessionmaker[Session]
) -> dict[str, str]:
    ids = {truth_id: _upload(client, truth_id)["id"] for truth_id in world.truth}
    run_until_empty(session_factory, world.services, worker_id="test")
    return ids


# --- basics --------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-Owner-Id": ""}, {"X-Owner-Id": "bad owner!"}])
def test_requests_without_a_valid_owner_are_rejected(
    client: TestClient, headers: dict[str, str]
) -> None:
    assert client.get("/documents", headers=headers).status_code == 401


# --- upload --------------------------------------------------------------------------


def test_upload_queues_the_document(client: TestClient) -> None:
    body = _upload(client, "set-001-po")
    assert body["status"] == "queued"
    assert body["filename"] == "set-001-po.pdf"
    assert body["job_id"]
    job = client.get(f"/jobs/{body['job_id']}", headers=A).json()
    assert job["status"] == "queued"


def test_uploading_the_same_file_twice_returns_the_existing_document(client: TestClient) -> None:
    first = _upload(client, "set-001-po")
    response = client.post(
        "/documents",
        headers=A,
        files={"file": ("again.pdf", fake_pdf("set-001-po"), "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["id"] == first["id"]
    assert response.json()["job_id"] is None


@pytest.mark.parametrize(
    ("name", "data"),
    [("notes.txt", b"hello"), ("fake.pdf", b"not really a pdf"), ("empty.pdf", b"")],
)
def test_only_pdfs_are_accepted(client: TestClient, name: str, data: bytes) -> None:
    response = client.post("/documents", headers=A, files={"file": (name, data, "application/pdf")})
    assert response.status_code == 415


# --- after processing ----------------------------------------------------------------


def test_full_flow_finds_the_injected_errors(
    client: TestClient, world: FakeWorld, session_factory: sessionmaker[Session]
) -> None:
    ids = _upload_all_and_process(client, world, session_factory)

    documents = client.get("/documents", headers=A).json()
    assert len(documents) == len(ids)
    assert {d["status"] for d in documents} == {"done"}

    findings = client.get("/discrepancies", headers=A).json()
    found = sorted((f["document_id"], f["type"]) for f in findings)
    expected = sorted((ids[e.document_id], e.type.value) for s in generate(42, 8) for e in s.errors)
    assert found == expected
    assert all(f["status"] == "open" and f["filename"].endswith(".pdf") for f in findings)


def test_document_detail_shows_fields_provenance_and_findings(
    client: TestClient, world: FakeWorld, session_factory: sessionmaker[Session]
) -> None:
    ids = _upload_all_and_process(client, world, session_factory)
    detail = client.get(f"/documents/{ids['set-003-inv-1']}", headers=A).json()

    assert detail["doc_type"] == "invoice"
    assert detail["document"]["invoice_number"] == world.truth["set-003-inv-1"].invoice_number  # type: ignore[union-attr]
    assert detail["extraction"]["model"] == "claude-haiku-5-5"
    assert detail["extraction"]["raw"]["doc_type"] == "invoice"
    assert "document_number" in detail["extraction"]["provenance"]
    assert [f["rule"] for f in detail["discrepancies"]] == ["R1"]
    assert detail["corrections"] == []


def test_the_original_file_can_be_downloaded(client: TestClient) -> None:
    doc = _upload(client, "set-001-po")
    response = client.get(f"/documents/{doc['id']}/file", headers=A)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == fake_pdf("set-001-po")


def test_filtering_findings_by_status(
    client: TestClient, world: FakeWorld, session_factory: sessionmaker[Session]
) -> None:
    _upload_all_and_process(client, world, session_factory)
    finding = client.get("/discrepancies", headers=A).json()[0]

    response = client.patch(
        f"/discrepancies/{finding['id']}", headers=A, json={"status": "dismissed"}
    )
    assert response.status_code == 200 and response.json()["status"] == "dismissed"
    assert len(client.get("/discrepancies?status=open", headers=A).json()) == 5
    assert len(client.get("/discrepancies?status=dismissed", headers=A).json()) == 1


# --- corrections ---------------------------------------------------------------------


def test_correcting_a_misread_value_clears_the_finding_and_keeps_the_raw_extraction(
    client: TestClient, world: FakeWorld, session_factory: sessionmaker[Session]
) -> None:
    ids = _upload_all_and_process(client, world, session_factory)
    doc_id = ids["set-003-inv-1"]
    [finding] = client.get(f"/discrepancies?document_id={doc_id}", headers=A).json()
    assert finding["field"] == "lines[1].quantity"

    # Say a person checks the paper invoice and it really says 8: correct the read value.
    # (The quantity, line net, VAT and totals must all change for a consistent invoice.)
    corrections = {
        "lines[1].quantity": "8",
        "lines[1].line_net": "£42.32",
        "lines[1].line_vat": "£8.46",
        "net_total": "£731.34",
        "vat_total": "£146.26",
        "gross_total": "£877.60",
    }
    for field, value in corrections.items():
        response = client.post(
            f"/documents/{doc_id}/corrections",
            headers=A,
            json={"field": field, "new_value": value, "author": "reviewer@example.com"},
        )
        assert response.status_code == 201, response.text

    detail = client.get(f"/documents/{doc_id}", headers=A).json()
    assert detail["discrepancies"] == []
    assert detail["document"]["lines"][1]["quantity"] == "8.0000"
    assert detail["extraction"]["raw"]["lines"][1]["quantity"] == "9"  # what the model read
    assert [c["field"] for c in detail["corrections"]] == list(corrections)
    assert detail["corrections"][0]["old_value"] == "9"


def test_correcting_an_unreadable_document_takes_it_out_of_review(
    client: TestClient, world: FakeWorld, session_factory: sessionmaker[Session]
) -> None:
    world.broken.add("set-002-po")
    ids = _upload_all_and_process(client, world, session_factory)
    doc_id = ids["set-002-po"]
    assert client.get(f"/documents/{doc_id}", headers=A).json()["status"] == "needs_review"

    supplier = world.truth["set-002-po"].supplier
    for field, value in {
        "supplier.name": supplier.name,
        "supplier.vat_number": supplier.vat_number,
        "supplier.address_line1": supplier.address.line1,
        "supplier.city": supplier.address.city,
        "supplier.postcode": supplier.address.postcode,
    }.items():
        client.post(
            f"/documents/{doc_id}/corrections",
            headers=A,
            json={"field": field, "new_value": value, "author": "reviewer@example.com"},
        )

    assert client.get(f"/documents/{doc_id}", headers=A).json()["status"] == "done"


def test_correcting_a_field_that_does_not_exist_is_rejected(
    client: TestClient, world: FakeWorld, session_factory: sessionmaker[Session]
) -> None:
    ids = _upload_all_and_process(client, world, session_factory)
    for field in ("no_such_field", "lines[99].quantity", "lines[0].colour"):
        response = client.post(
            f"/documents/{ids['set-003-inv-1']}/corrections",
            headers=A,
            json={"field": field, "new_value": "1", "author": "x"},
        )
        assert response.status_code == 422, field


# --- tenancy -------------------------------------------------------------------------


def test_owners_cannot_see_or_touch_each_others_data(
    client: TestClient, world: FakeWorld, session_factory: sessionmaker[Session]
) -> None:
    ids = _upload_all_and_process(client, world, session_factory)
    doc_id = ids["set-003-inv-1"]
    finding = client.get("/discrepancies", headers=A).json()[0]

    assert client.get("/documents", headers=B).json() == []
    assert client.get("/discrepancies", headers=B).json() == []
    # 404, not 403: another owner must not even learn that the id exists.
    assert client.get(f"/documents/{doc_id}", headers=B).status_code == 404
    assert client.get(f"/documents/{doc_id}/file", headers=B).status_code == 404
    assert (
        client.patch(
            f"/discrepancies/{finding['id']}", headers=B, json={"status": "dismissed"}
        ).status_code
        == 404
    )
    response = client.post(
        f"/documents/{doc_id}/corrections",
        headers=B,
        json={"field": "net_total", "new_value": "1", "author": "x"},
    )
    assert response.status_code == 404
