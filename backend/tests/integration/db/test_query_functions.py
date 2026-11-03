from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.db.mapping import document_to_row
from backend.app.db.models import DiscrepancyRow, DocumentRow
from backend.app.domain.document_set import DocumentSet
from backend.app.query.functions import find_documents, invoice_totals, list_findings
from backend.app.validation.rules import Document
from data_generator.generate import generate

OWNER = "owner-a"


def _load(session: Session, owner: str = OWNER) -> list[DocumentSet]:
    sets = list(generate(42, 8))
    for s in sets:
        docs: list[Document] = [s.purchase_order, s.delivery_note, *s.invoices]
        for doc in docs:
            session.add(
                DocumentRow(
                    id=f"{owner}:{doc.document_id}",
                    owner_id=owner,
                    filename=f"{doc.document_id}.pdf",
                    sha256=f"{owner}:{doc.document_id}"[:64],
                    status="done",
                    doc_type=doc.doc_type,
                )
            )
            session.flush()
            session.add(
                document_to_row(
                    doc.model_copy(update={"document_id": f"{owner}:{doc.document_id}"}), owner
                )
            )
    session.flush()
    return sets


def test_totals_for_everything_and_per_supplier(session: Session) -> None:
    sets = _load(session)
    invoices = [i for s in sets for i in s.invoices]

    everything = invoice_totals(session, OWNER)
    assert everything.count == len(invoices)
    assert everything.gross == sum((i.gross_total for i in invoices), Decimal(0))

    name = invoices[0].supplier.name
    first_word = name.split()[0].lower()  # "kestrel" style partial, lower case
    one = invoice_totals(session, OWNER, supplier=first_word)
    expected = [i for i in invoices if i.supplier.name == name]
    assert one.count == len(expected)
    assert one.gross == sum((i.gross_total for i in expected), Decimal(0))
    assert one.suppliers == [name]


def test_totals_by_date_range_are_inclusive(session: Session) -> None:
    invoices = [i for s in _load(session) for i in s.invoices]
    day = invoices[0].issue_date
    same_day = invoice_totals(session, OWNER, date_from=day, date_to=day)
    assert same_day.count == sum(i.issue_date == day for i in invoices)
    assert invoice_totals(session, OWNER, date_from=date(2030, 1, 1)).count == 0


def test_like_wildcards_in_names_are_literal(session: Session) -> None:
    _load(session)
    assert invoice_totals(session, OWNER, supplier="%").count == 0
    assert invoice_totals(session, OWNER, supplier="_").count == 0


def test_find_documents_ignores_hyphens_spaces_and_case(session: Session) -> None:
    sets = _load(session)
    invoice = sets[2].invoices[0]
    number = invoice.invoice_number.lower().replace("-", " ")
    [found] = find_documents(session, OWNER, number)
    assert (found.doc_type, found.number) == ("invoice", invoice.invoice_number)
    assert find_documents(session, OWNER, "INV-0000-00000") == []


def test_owner_scope(session: Session) -> None:
    sets = _load(session, "owner-a")
    assert invoice_totals(session, "owner-b").count == 0
    assert find_documents(session, "owner-b", sets[0].invoices[0].invoice_number) == []


def test_findings_by_status_and_supplier(session: Session) -> None:
    sets = _load(session)
    invoice = sets[2].invoices[0]
    session.add_all(
        [
            DiscrepancyRow(
                owner_id=OWNER,
                document_id=f"{OWNER}:{invoice.document_id}",
                rule="R1",
                type="quantity_mismatch",
                message="m",
                status="open",
            ),
            DiscrepancyRow(
                owner_id=OWNER,
                document_id=f"{OWNER}:{sets[3].invoices[0].document_id}",
                rule="R2",
                type="unit_price_mismatch",
                message="m",
                status="dismissed",
            ),
        ]
    )
    session.flush()
    assert [f.rule for f in list_findings(session, OWNER)] == ["R1"]
    assert {f.rule for f in list_findings(session, OWNER, status="any")} == {"R1", "R2"}
    supplier = invoice.supplier.name.split()[0]
    assert [f.rule for f in list_findings(session, OWNER, status="any", supplier=supplier)] == [
        "R1"
    ] or (sets[3].invoices[0].supplier.name.startswith(supplier))
