from backend.app.ingestion.models import (
    BBox,
    Page,
    ParsedDocument,
    Provenance,
    Table,
    TableCell,
    TextBlock,
)

PROV = Provenance(page=1, bbox=BBox(left=10, top=20, right=110, bottom=40))


def _cell(row: int, col: int, text: str) -> TableCell:
    return TableCell(row=row, col=col, text=text, is_header=row == 0, prov=PROV)


def _table() -> Table:
    # Cells deliberately out of order: rows() must place them by row/col.
    cells = (
        _cell(1, 1, "£5.29"),
        _cell(0, 0, "Code"),
        _cell(1, 0, "WH-3008"),
        _cell(0, 1, "Price"),
    )
    return Table(n_rows=2, n_cols=2, cells=cells, prov=PROV)


def _doc() -> ParsedDocument:
    return ParsedDocument(
        source="inv-1.pdf",
        sha256="0" * 64,
        parser="docling 0.0.0",
        ocr=False,
        pages=(Page(number=1, width=595, height=842),),
        elements=(
            TextBlock(label="section_header", text="INVOICE", prov=PROV),
            _table(),
            TextBlock(label="text", text="Total Due £883.95", prov=PROV),
        ),
        markdown="# INVOICE",
    )


def test_table_rows_are_built_from_cell_positions() -> None:
    assert _table().rows() == [["Code", "Price"], ["WH-3008", "£5.29"]]


def test_table_rows_leave_missing_cells_empty() -> None:
    table = Table(n_rows=2, n_cols=2, cells=(_cell(0, 0, "Code"),), prov=PROV)
    assert table.rows() == [["Code", ""], ["", ""]]


def test_full_text_includes_blocks_and_table_cells_in_order() -> None:
    assert _doc().full_text() == "INVOICE\nCode | Price\nWH-3008 | £5.29\nTotal Due £883.95"


def test_tables_helper() -> None:
    assert _doc().tables() == [_table()]


def test_json_round_trip_keeps_element_types() -> None:
    doc = _doc()
    restored = ParsedDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc
    assert isinstance(restored.elements[1], Table)
