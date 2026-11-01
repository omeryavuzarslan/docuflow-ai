"""Runs the real Docling models, so it is slow (model load + OCR): `uv run pytest -m slow`."""

import hashlib
from pathlib import Path

import pytest

from backend.app.domain.documents import Invoice
from backend.app.ingestion.models import ParsedDocument
from backend.app.ingestion.parse import has_text_layer, parse_pdf
from data_generator.build import build_clean_set
from data_generator.plan import SetPlan
from data_generator.render import render_pdf
from data_generator.scan import make_scan


@pytest.fixture(scope="module")
def invoice() -> Invoice:
    plan = SetPlan(index=1, template="classic", error_type=None, partial_delivery=False)
    return build_clean_set(42, plan).invoices[0]


@pytest.fixture(scope="module")
def pdfs(invoice: Invoice, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("pdfs")
    digital = render_pdf(invoice, "classic")
    paths = {"digital": root / "inv.pdf", "scan": root / "inv.scan.pdf"}
    paths["digital"].write_bytes(digital)
    paths["scan"].write_bytes(make_scan(digital, "test"))
    return paths


def test_text_layer_detection(pdfs: dict[str, Path]) -> None:
    assert has_text_layer(pdfs["digital"])
    assert not has_text_layer(pdfs["scan"])


def _assert_well_formed(parsed: ParsedDocument, path: Path) -> None:
    assert parsed.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert parsed.parser.startswith("docling ")
    assert [page.number for page in parsed.pages] == [1]
    page = parsed.pages[0]
    for element in parsed.elements:
        box = element.prov.bbox
        assert element.prov.page == 1
        assert 0 <= box.left < box.right <= page.width
        assert 0 <= box.top < box.bottom <= page.height


@pytest.mark.slow
def test_digital_pdf(pdfs: dict[str, Path], invoice: Invoice) -> None:
    parsed = parse_pdf(pdfs["digital"])
    _assert_well_formed(parsed, pdfs["digital"])
    assert parsed.ocr is False
    text = parsed.full_text()
    assert invoice.invoice_number in text
    assert "£" + f"{invoice.gross_total:,.2f}" in text

    line_table = next(t for t in parsed.tables() if t.n_rows == len(invoice.lines) + 1)
    rows = line_table.rows()
    assert "Qty" in rows[0]
    assert [row[1] for row in rows[1:]] == [line.sku for line in invoice.lines]
    for cell in line_table.cells:
        assert cell.prov.bbox.left < cell.prov.bbox.right


@pytest.mark.slow
def test_scanned_pdf_uses_ocr(pdfs: dict[str, Path], invoice: Invoice) -> None:
    parsed = parse_pdf(pdfs["scan"])
    _assert_well_formed(parsed, pdfs["scan"])
    assert parsed.ocr is True
    text = parsed.full_text()
    found = sum(line.sku in text for line in invoice.lines)
    assert found >= 0.75 * len(invoice.lines)
    assert parsed.tables()
