from backend.app.domain.documents import Invoice
from backend.app.ingestion.models import (
    BBox,
    Page,
    ParsedDocument,
    Provenance,
    Table,
    TableCell,
    TextBlock,
)
from backend.tests.unit.domain.factories import make_invoice
from data_generator.render import format_money
from eval.runners.parse_eval import expected_values, score

PROV = Provenance(page=1, bbox=BBox(left=0, top=0, right=1, bottom=1))


def _parsed(header_text: str, rows: list[list[str]]) -> ParsedDocument:
    cells = tuple(
        TableCell(row=r, col=c, text=text, is_header=r == 0, prov=PROV)
        for r, row in enumerate(rows)
        for c, text in enumerate(row)
    )
    table = Table(n_rows=len(rows), n_cols=len(rows[0]), cells=cells, prov=PROV)
    return ParsedDocument(
        source="x.pdf",
        sha256="0" * 64,
        parser="test",
        ocr=False,
        pages=(Page(number=1, width=595, height=842),),
        elements=(TextBlock(label="text", text=header_text, prov=PROV), table),
        markdown="",
    )


def _perfect(invoice: Invoice) -> ParsedDocument:
    header, lines = expected_values(invoice)
    rows = [["Code", "Qty", "Price", "Net", "VAT"]] + [[sku, *values] for sku, values in lines]
    return _parsed(" ".join(header), rows)


def test_invoice_expected_values_are_formatted_like_the_pdf() -> None:
    header, lines = expected_values(make_invoice())
    assert format_money(make_invoice().gross_total) in header
    assert lines[0] == ("SKU-001", ["3", "£19.99", "£59.97", "£11.99"])


def test_perfect_parse_scores_everything() -> None:
    invoice = make_invoice()
    found, total, missed, line_table = score(invoice, _perfect(invoice))
    assert (found, total, missed, line_table) == (total, 7 + 2 * 5, [], True)


def test_value_in_the_wrong_row_does_not_count() -> None:
    invoice = make_invoice()
    header, _ = expected_values(invoice)
    # Line 1's quantity "3" only appears in line 2's row.
    rows = [
        ["Code", "Qty", "Price", "Net", "VAT"],
        ["SKU-001", "", "£19.99", "£59.97", "£11.99"],
        ["SKU-002", "2 3", "£5.125", "£10.25", "£2.05"],
    ]
    _, _, missed, _ = score(invoice, _parsed(" ".join(header), rows))
    assert missed == ["SKU-001:3"]


def test_missing_header_value_and_whitespace_differences() -> None:
    invoice = make_invoice()
    header, lines = expected_values(invoice)
    text = "  ".join(h for h in header if h != invoice.invoice_number)  # double spaces are fine
    rows = [["Code"]] + [[f"{sku}   {' '.join(values)}"] for sku, values in lines]
    _, _, missed, _ = score(invoice, _parsed(text, rows))
    assert missed == [invoice.invoice_number]
