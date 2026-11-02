from backend.app.rag.chunking import document_context, fixed_chunks, structure_chunks
from backend.tests.unit.rag.helpers import agreement_like


def test_context_is_the_title_and_reference_line() -> None:
    assert document_context(agreement_like()) == (
        "FRAMEWORK SUPPLY AGREEMENT · SA-2025-001 · "
        "Kestrel Office Supplies Ltd and Harbour & Hale Retail plc"
    )


def test_one_chunk_per_section_with_the_document_context_in_front() -> None:
    chunks = structure_chunks(agreement_like())
    sections = [c for c in chunks if c.kind == "section"]
    assert [c.heading for c in sections] == [
        "FRAMEWORK SUPPLY AGREEMENT",
        "4. Invoicing and payment",
        "6. Termination",
        "Schedule 1: Price list",
    ]
    payment = sections[1]
    assert payment.body == (
        "Payment terms are 60 days from the date of invoice.\n"
        "Interest on overdue sums runs at 6% per annum."
    )
    # What is embedded carries the contract's identity, so 15 near-identical payment
    # clauses can still be told apart.
    assert payment.text.startswith("FRAMEWORK SUPPLY AGREEMENT · SA-2025-001 · Kestrel")
    assert "4. Invoicing and payment" in payment.text
    assert payment.page == 1


def test_page_footers_are_left_out() -> None:
    assert all("Page 1 of 2" not in c.text for c in structure_chunks(agreement_like()))


def test_each_table_row_is_its_own_chunk_with_column_names() -> None:
    rows = [c for c in structure_chunks(agreement_like()) if c.kind == "row"]
    assert [r.body for r in rows] == [
        "Item Code: OF-1001 | Description: A4 copier paper | Unit Price: £25.28",
        "Item Code: OF-1002 | Description: Pens | Unit Price: £7.99",
    ]
    assert rows[0].heading == "Schedule 1: Price list"
    assert rows[0].page == 2
    assert rows[0].text.startswith("FRAMEWORK SUPPLY AGREEMENT · SA-2025-001")


def test_ordinals_follow_reading_order() -> None:
    chunks = structure_chunks(agreement_like())
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_fixed_chunks_cover_the_text_with_overlap_and_no_context() -> None:
    parsed = agreement_like()
    chunks = fixed_chunks(parsed, size=80, overlap=20)
    assert all(c.kind == "fixed" and len(c.body) <= 80 for c in chunks)
    assert chunks[0].text == chunks[0].body  # the baseline adds nothing
    assert chunks[1].body[:20] == chunks[0].body[-20:]  # overlap
    joined = chunks[0].body + "".join(c.body[20:] for c in chunks[1:])
    assert "Payment terms are 60 days" in joined
