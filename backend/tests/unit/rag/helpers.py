import hashlib
import math
import re

from backend.app.ingestion.models import (
    BBox,
    Page,
    ParsedDocument,
    Provenance,
    Table,
    TableCell,
    TextBlock,
)


def prov(page: int = 1, n: float = 0) -> Provenance:
    return Provenance(page=page, bbox=BBox(left=n, top=n, right=n + 10, bottom=n + 5))


def agreement_like() -> ParsedDocument:
    """Shaped like Docling's parse of a generated supplier agreement."""
    rows = [
        ["Item Code", "Description", "Unit Price"],
        ["OF-1001", "A4 copier paper", "£25.28"],
        ["OF-1002", "Pens", "£7.99"],
    ]
    cells = tuple(
        TableCell(row=r, col=c, text=t, is_header=r == 0, prov=prov(2, 100 + r))
        for r, row in enumerate(rows)
        for c, t in enumerate(row)
    )
    return ParsedDocument(
        source="agreement-001.pdf",
        sha256="a" * 64,
        parser="test",
        ocr=False,
        pages=(Page(number=1, width=595, height=842), Page(number=2, width=595, height=842)),
        elements=(
            TextBlock(label="section_header", text="FRAMEWORK SUPPLY AGREEMENT", prov=prov(1, 1)),
            TextBlock(
                label="text",
                text="SA-2025-001 · Kestrel Office Supplies Ltd and Harbour & Hale Retail plc",
                prov=prov(1, 2),
            ),
            TextBlock(label="section_header", text="4. Invoicing and payment", prov=prov(1, 3)),
            TextBlock(
                label="text",
                text="Payment terms are 60 days from the date of invoice.",
                prov=prov(1, 4),
            ),
            TextBlock(
                label="text", text="Interest on overdue sums runs at 6% per annum.", prov=prov(1, 5)
            ),
            TextBlock(label="section_header", text="6. Termination", prov=prov(1, 6)),
            TextBlock(
                label="text",
                text="Either party may end this agreement by giving 60 days' written notice.",
                prov=prov(1, 7),
            ),
            TextBlock(label="page_footer", text="Page 1 of 2", prov=prov(1, 8)),
            TextBlock(label="section_header", text="Schedule 1: Price list", prov=prov(2, 9)),
            TextBlock(label="text", text="Agreed unit prices, excluding VAT.", prov=prov(2, 10)),
            Table(n_rows=3, n_cols=3, cells=cells, prov=prov(2, 100)),
        ),
        markdown="",
    )


class FakeEmbedder:
    """Deterministic bag-of-words vectors: texts sharing words are close. No model download."""

    model_name = "fake-bow"
    dim = 384

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
