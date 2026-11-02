"""Split a parsed document into chunks for retrieval.

Two strategies, so their effect can be measured (docs/experiments.md):

structure  One chunk per section (a heading and the text under it) and one per table row,
           with column names. Every chunk starts with the document's context line (title +
           reference, e.g. "FRAMEWORK SUPPLY AGREEMENT · SA-2025-001 · Kestrel ... and
           Harbour & Hale ..."): fifteen agreements have near-identical payment clauses, and
           without that line a correct clause from the wrong contract looks just as good.
structure_no_context
           The same chunks without the context line, to measure what that line is worth.
fixed      The usual baseline: the plain text cut into overlapping windows of N characters.

`text` is what gets embedded; `body` is the part shown to a person.
Page footers ("Page 1 of 2") carry nothing and are left out of both.
"""

from typing import Literal

from backend.app.domain.types import DomainModel
from backend.app.ingestion.models import BBox, ParsedDocument, Table, TextBlock

Strategy = Literal["structure", "structure_no_context", "fixed"]
SKIPPED_LABELS = {"page_footer"}
CONTEXT_MAX_CHARS = 200


class Chunk(DomainModel):
    ordinal: int
    kind: Literal["section", "row", "fixed"]
    heading: str
    body: str
    text: str
    page: int
    bbox: BBox


def chunk(parsed: ParsedDocument, strategy: Strategy = "structure") -> list[Chunk]:
    if strategy == "fixed":
        return fixed_chunks(parsed)
    return structure_chunks(parsed, with_context=strategy == "structure")


def _elements(parsed: ParsedDocument) -> list[TextBlock | Table]:
    return [
        e for e in parsed.elements if not (isinstance(e, TextBlock) and e.label in SKIPPED_LABELS)
    ]


def document_context(parsed: ParsedDocument) -> str:
    """The first heading and the line after it, or the first two lines."""
    texts = [e for e in _elements(parsed) if isinstance(e, TextBlock)]
    heading = next((i for i, e in enumerate(texts) if e.label in ("section_header", "title")), 0)
    parts = [e.text for e in texts[heading : heading + 2]]
    return " · ".join(" ".join(p.split()) for p in parts)[:CONTEXT_MAX_CHARS]


def structure_chunks(parsed: ParsedDocument, with_context: bool = True) -> list[Chunk]:
    context = document_context(parsed) if with_context else ""
    chunks: list[Chunk] = []
    heading: str = ""
    body: list[str] = []
    first: TextBlock | Table | None = None

    def emit(
        kind: Literal["section", "row"], head: str, text: str, element: TextBlock | Table
    ) -> None:
        chunks.append(
            Chunk(
                ordinal=len(chunks),
                kind=kind,
                heading=head,
                body=text,
                text="\n".join(part for part in (context, head, text) if part),
                page=element.prov.page,
                bbox=element.prov.bbox,
            )
        )

    def flush() -> None:
        if body and first is not None:
            emit("section", heading, "\n".join(body), first)

    for element in _elements(parsed):
        if isinstance(element, Table):
            flush()
            body, first = [], None
            rows = element.rows()
            header, data = (rows[0], rows[1:]) if len(rows) > 1 else ([], rows)
            for row in data:
                cells = [
                    f"{h}: {v}" if h else v
                    for h, v in zip(header or [""] * len(row), row, strict=False)
                ]
                emit("row", heading, " | ".join(cells), element)
        elif element.label in ("section_header", "title"):
            flush()
            heading, body, first = element.text, [], element
        else:
            body.append(element.text)
            first = first or element
    flush()
    return chunks


def fixed_chunks(parsed: ParsedDocument, size: int = 500, overlap: int = 100) -> list[Chunk]:
    pieces: list[tuple[str, TextBlock | Table]] = []
    for element in _elements(parsed):
        if isinstance(element, Table):
            pieces.append(("\n".join(" | ".join(r) for r in element.rows()), element))
        else:
            pieces.append((element.text, element))

    text, starts = "", []  # starts: (offset, element) to find the page of a window
    for piece, element in pieces:
        starts.append((len(text), element))
        text += piece + "\n"

    chunks: list[Chunk] = []
    step = size - overlap
    for start in range(0, max(len(text) - overlap, 1), step):
        window = text[start : start + size]
        element = [e for offset, e in starts if offset <= start][-1]
        chunks.append(
            Chunk(
                ordinal=len(chunks),
                kind="fixed",
                heading="",
                body=window,
                text=window,
                page=element.prov.page,
                bbox=element.prov.bbox,
            )
        )
    return chunks
