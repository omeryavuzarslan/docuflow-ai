"""Real embedding model (bge-small, local, free) on the 15 generated agreements.
Slow: loads the model. `uv run pytest -m slow`."""

import math

import pytest

from backend.app.domain.agreements import SupplierAgreement
from backend.app.ingestion.models import BBox, Page, ParsedDocument, Provenance, TextBlock
from backend.app.rag.chunking import Chunk, structure_chunks
from backend.app.rag.embeddings import LocalEmbedder
from data_generator.agreements import build_agreements

PROV = Provenance(page=1, bbox=BBox(left=0, top=0, right=1, bottom=1))


def _parsed(a: SupplierAgreement) -> ParsedDocument:
    """The agreement as Docling would parse it: title, reference line, then sections."""
    elements = [
        TextBlock(label="section_header", text="FRAMEWORK SUPPLY AGREEMENT", prov=PROV),
        TextBlock(
            label="text",
            text=f"{a.agreement_number} · {a.supplier.name} and {a.buyer.name}",
            prov=PROV,
        ),
    ]
    for s in a.sections:
        elements.append(
            TextBlock(label="section_header", text=f"{s.number}. {s.heading}", prov=PROV)
        )
        elements.append(TextBlock(label="text", text=s.text, prov=PROV))
    return ParsedDocument(
        source=f"{a.document_id}.pdf",
        sha256="0" * 64,
        parser="test",
        ocr=False,
        pages=(Page(number=1, width=595, height=842),),
        elements=tuple(elements),
        markdown="",
    )


@pytest.mark.slow
def test_finds_the_right_clause_of_the_right_contract() -> None:
    embedder = LocalEmbedder()
    agreements = build_agreements(42)
    corpus: list[tuple[str, Chunk]] = [
        (a.document_id, c) for a in agreements for c in structure_chunks(_parsed(a))
    ]
    vectors = embedder.embed_documents([c.text for _, c in corpus])

    target = agreements[0]  # Kestrel Office Supplies -> Harbour & Hale
    query = (
        f"How many days does {target.buyer.name} have to pay invoices from {target.supplier.name}?"
    )
    q = embedder.embed_query(query)
    scores = [sum(x * y for x, y in zip(q, v, strict=True)) for v in vectors]
    best = max(range(len(corpus)), key=scores.__getitem__)

    document_id, chunk = corpus[best]
    assert document_id == target.document_id
    assert chunk.heading == "4. Invoicing and payment"
    assert f"{target.payment_terms_days} days" in chunk.body
    assert all(math.isfinite(s) for s in scores)
