"""PDF -> ParsedDocument, using Docling.

Digital PDFs carry their text, so we read it directly (fast and exact). Image-only PDFs
(scans) have no text layer; for those we run full-page OCR. `parse_pdf` detects which
case it is unless told.

This is the only module that imports Docling.
"""

import hashlib
import importlib.metadata
from functools import cache
from pathlib import Path

import pypdfium2 as pdfium
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import OcrAutoOptions, OcrMode, PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DoclingDocument,
    ProvenanceItem,
    TableItem,
    TextItem,
)

from backend.app.ingestion.models import (
    BBox,
    Element,
    Page,
    ParsedDocument,
    Provenance,
    Table,
    TableCell,
    TextBlock,
)

PARSER = f"docling {importlib.metadata.version('docling')}"


def has_text_layer(path: Path) -> bool:
    """True if any page has embedded text (a digital PDF rather than a scan)."""
    pdf = pdfium.PdfDocument(path)
    try:
        return any(page.get_textpage().count_chars() > 0 for page in pdf)
    finally:
        pdf.close()


def parse_pdf(path: Path, ocr: bool | None = None) -> ParsedDocument:
    """Parse a PDF. `ocr=None` decides from the text layer: OCR only when there is none."""
    use_ocr = not has_text_layer(path) if ocr is None else ocr
    result = _converter(use_ocr).convert(path)
    document = result.document
    pages = tuple(
        Page(number=number, width=page.size.width, height=page.size.height)
        for number, page in sorted(document.pages.items())
    )
    return ParsedDocument(
        source=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        parser=PARSER,
        ocr=use_ocr,
        pages=pages,
        elements=tuple(_elements(document, pages)),
        markdown=document.export_to_markdown(),
    )


@cache
def _converter(ocr: bool) -> DocumentConverter:
    # Loading the models takes seconds, so each configuration is built once and reused.
    options = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True)
    if ocr:
        # "auto" picks an installed engine (RapidOCR here). Full-page OCR, because a scan
        # is one big image with no text to fall back on.
        options.ocr_options = OcrAutoOptions(mode=OcrMode.FULL_PAGE)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def _elements(document: DoclingDocument, pages: tuple[Page, ...]) -> list[Element]:
    elements: list[Element] = []
    for item, _level in document.iterate_items():
        if not isinstance(item, TextItem | TableItem) or not item.prov:
            continue  # pictures, groups, and anything without a position
        prov = _provenance(item.prov[0], pages)
        if isinstance(item, TableItem):
            elements.append(_table(item, prov, pages))
        elif item.text.strip():
            elements.append(TextBlock(label=str(item.label), text=item.text, prov=prov))
    return elements


def _table(item: TableItem, prov: Provenance, pages: tuple[Page, ...]) -> Table:
    cells = tuple(
        TableCell(
            row=cell.start_row_offset_idx,
            col=cell.start_col_offset_idx,
            text=cell.text,
            is_header=cell.column_header,
            # A cell without its own box falls back to the table's box.
            prov=Provenance(page=prov.page, bbox=_bbox(cell.bbox, pages[prov.page - 1]))
            if cell.bbox is not None
            else prov,
        )
        for cell in item.data.table_cells
    )
    return Table(n_rows=item.data.num_rows, n_cols=item.data.num_cols, cells=cells, prov=prov)


def _provenance(prov: ProvenanceItem, pages: tuple[Page, ...]) -> Provenance:
    return Provenance(page=prov.page_no, bbox=_bbox(prov.bbox, pages[prov.page_no - 1]))


def _bbox(box: BoundingBox, page: Page) -> BBox:
    """Docling mixes origins (PDF items bottom-left, table cells top-left); we use top-left.

    Clamped to the page: OCR on a slightly rotated scan can report a box a fraction of a
    point outside it, which is meaningless for highlighting.
    """
    if box.coord_origin == CoordOrigin.BOTTOMLEFT:
        box = box.to_top_left_origin(page_height=page.height)
    return BBox(
        left=min(max(box.l, 0.0), page.width),
        top=min(max(box.t, 0.0), page.height),
        right=min(max(box.r, 0.0), page.width),
        bottom=min(max(box.b, 0.0), page.height),
    )
