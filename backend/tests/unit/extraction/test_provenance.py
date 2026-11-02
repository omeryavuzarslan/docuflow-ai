from backend.app.extraction.provenance import locate
from backend.app.extraction.schema import ExtractedDocument, ExtractedLine
from backend.app.ingestion.models import (
    BBox,
    Page,
    ParsedDocument,
    Provenance,
    Table,
    TableCell,
    TextBlock,
)


def _prov(n: float) -> Provenance:
    return Provenance(page=1, bbox=BBox(left=n, top=n, right=n + 10, bottom=n + 5))


def _parsed() -> ParsedDocument:
    rows = [
        ["Code", "Qty", "Unit Price", "Net"],
        ["WH-3008", "9", "£5.29", "£47.61"],
        ["WH-3009", "9", "£4.78", "£43.02"],
    ]
    cells = tuple(
        TableCell(row=r, col=c, text=t, is_header=r == 0, prov=_prov(100 + 10 * r + c))
        for r, row in enumerate(rows)
        for c, t in enumerate(row)
    )
    table = Table(n_rows=3, n_cols=4, cells=cells, prov=_prov(90))
    return ParsedDocument(
        source="x.pdf",
        sha256="0" * 64,
        parser="test",
        ocr=False,
        pages=(Page(number=1, width=595, height=842),),
        elements=(
            TextBlock(label="text", text="Invoice Number: INV-2026-00379", prov=_prov(10)),
            table,
            TextBlock(label="text", text="Total Due £90.63", prov=_prov(50)),
        ),
        markdown="",
    )


def _extracted(**changes: object) -> ExtractedDocument:
    base = ExtractedDocument(
        doc_type="invoice",
        document_number="INV-2026-00379",
        gross_total="£90.63",
        lines=(
            ExtractedLine(sku="WH-3008", quantity="9", unit_price="£5.29", line_net="£47.61"),
            ExtractedLine(sku="WH-3009", quantity="9", unit_price="£4.78", line_net="£43.02"),
        ),
    )
    return base.model_copy(update=changes)


def test_header_values_point_at_their_text_block() -> None:
    found = locate(_parsed(), _extracted())
    assert found["document_number"] == _prov(10)
    assert found["gross_total"] == _prov(50)


def test_line_values_point_at_the_cell_in_their_own_row() -> None:
    found = locate(_parsed(), _extracted())
    # Both lines have quantity "9": each must resolve to its own row's cell.
    assert found["lines[0].quantity"] == _prov(100 + 10 * 1 + 1)
    assert found["lines[1].quantity"] == _prov(100 + 10 * 2 + 1)
    assert found["lines[1].sku"] == _prov(100 + 10 * 2 + 0)


def test_values_not_on_the_page_are_unverified() -> None:
    lines = (
        ExtractedLine(sku="WH-3008", quantity="12"),
        ExtractedLine(sku="XX-9999", quantity="9"),
    )
    found = locate(_parsed(), _extracted(gross_total="£999.99", lines=lines))
    assert found["gross_total"] is None
    assert found["lines[0].quantity"] is None  # "12" is not in WH-3008's row
    assert found["lines[1].sku"] is None
    assert found["lines[1].quantity"] is None  # no row to look in


def test_missing_values_are_not_listed() -> None:
    found = locate(_parsed(), _extracted())
    assert "due_date" not in found
    assert "lines[0].line_vat" not in found
