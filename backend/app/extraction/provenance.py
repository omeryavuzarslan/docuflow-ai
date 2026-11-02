"""Find where on the page each extracted value came from.

The LLM returns values, not coordinates. Python looks each value up in the parsed document:
line values in the table row of their SKU, header values in table cells or text blocks.
A value that cannot be found is recorded as None ("unverified"): either the parser and the
LLM disagree, or the LLM produced something that is not on the page.
"""

from backend.app.extraction.schema import ExtractedDocument
from backend.app.ingestion.models import ParsedDocument, Provenance, Table, TableCell, TextBlock

_HEADER_FIELDS = (
    "document_number",
    "po_reference",
    "issue_date",
    "due_date",
    "net_total",
    "vat_total",
    "gross_total",
)
_LINE_FIELDS = (
    "line_no",
    "sku",
    "description",
    "quantity",
    "unit_price",
    "vat_rate",
    "line_net",
    "line_vat",
)


def locate(parsed: ParsedDocument, raw: ExtractedDocument) -> dict[str, Provenance | None]:
    """{field path: where it was found, or None}. Fields the LLM left empty are omitted."""
    found: dict[str, Provenance | None] = {}
    cells = [cell for table in parsed.tables() for cell in table.cells]
    blocks = [e for e in parsed.elements if isinstance(e, TextBlock)]

    for name in _HEADER_FIELDS:
        value = getattr(raw, name)
        if value:
            found[name] = _find_anywhere(value, cells, blocks)
    for i, ref in enumerate(raw.delivery_note_references):
        found[f"delivery_note_references[{i}]"] = _find_anywhere(ref, cells, blocks)
    for role in ("supplier", "buyer"):
        party = getattr(raw, role)
        for name in ("name", "vat_number"):
            value = getattr(party, name)
            if value:
                found[f"{role}.{name}"] = _find_anywhere(value, cells, blocks)

    for i, line in enumerate(raw.lines):
        row = _row_of(parsed.tables(), line.sku) if line.sku else None
        for name in _LINE_FIELDS:
            value = getattr(line, name)
            if value:
                found[f"lines[{i}].{name}"] = _find_in(value, row) if row else None
    return found


def _norm(text: str) -> str:
    return " ".join(text.split())


def _find_anywhere(
    value: str, cells: list[TableCell], blocks: list[TextBlock]
) -> Provenance | None:
    target = _norm(value)
    for cell in cells:
        if _norm(cell.text) == target:
            return cell.prov
    for block in blocks:
        if target in _norm(block.text):
            return block.prov
    return _find_in(value, cells)


def _find_in(value: str, cells: list[TableCell]) -> Provenance | None:
    """Exact cell match first, then a cell that contains the value."""
    target = _norm(value)
    for cell in cells:
        if _norm(cell.text) == target:
            return cell.prov
    for cell in cells:
        if target in _norm(cell.text):
            return cell.prov
    return None


def _row_of(tables: list[Table], sku: str) -> list[TableCell] | None:
    """The cells of the first table row that has a cell equal to the SKU."""
    target = _norm(sku)
    for table in tables:
        for cell in table.cells:
            if _norm(cell.text) == target:
                return [c for c in table.cells if c.row == cell.row]
    return None
