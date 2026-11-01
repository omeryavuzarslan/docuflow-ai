"""Our own representation of a parsed PDF.

The rest of the system depends on these models, never on Docling's types, so the parser
can be swapped without touching extraction or the UI.

Coordinates are PDF points (1/72 inch) with the origin at the TOP-LEFT of the page, the
convention browsers and image tools use, so the UI can draw highlight boxes directly.
They are floats: positions on a page, not money.
"""

from typing import Annotated, Literal

from pydantic import Field

from backend.app.domain.types import DomainModel


class BBox(DomainModel):
    left: float
    top: float
    right: float
    bottom: float


class Provenance(DomainModel):
    """Where on which page something was read from."""

    page: int = Field(ge=1)
    bbox: BBox


class Page(DomainModel):
    number: int = Field(ge=1)
    width: float
    height: float


class TextBlock(DomainModel):
    kind: Literal["text"] = "text"
    label: str  # Docling's layout label: "text", "section_header", "title", ...
    text: str
    prov: Provenance


class TableCell(DomainModel):
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    text: str
    is_header: bool
    prov: Provenance


class Table(DomainModel):
    kind: Literal["table"] = "table"
    n_rows: int
    n_cols: int
    cells: tuple[TableCell, ...]
    prov: Provenance

    def rows(self) -> list[list[str]]:
        """The table as a grid of strings; positions with no cell are empty."""
        grid = [["" for _ in range(self.n_cols)] for _ in range(self.n_rows)]
        for cell in self.cells:
            grid[cell.row][cell.col] = cell.text
        return grid


# `kind` tells Pydantic which class to build when reading JSON back.
Element = Annotated[TextBlock | Table, Field(discriminator="kind")]


class ParsedDocument(DomainModel):
    source: str  # file name
    sha256: str  # of the file bytes; part of the future LLM cache key
    parser: str  # e.g. "docling 2.145.0", so results can be traced to a version
    ocr: bool
    pages: tuple[Page, ...]
    elements: tuple[Element, ...]  # in reading order
    markdown: str  # Docling's Markdown export, the compact form we will give the LLM

    def tables(self) -> list[Table]:
        return [e for e in self.elements if isinstance(e, Table)]

    def full_text(self) -> str:
        """All text in reading order; table rows joined with " | "."""
        parts: list[str] = []
        for element in self.elements:
            if isinstance(element, Table):
                parts.extend(" | ".join(row) for row in element.rows())
            else:
                parts.append(element.text)
        return "\n".join(parts)
