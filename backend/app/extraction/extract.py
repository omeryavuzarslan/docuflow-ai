"""ParsedDocument -> ExtractionRecord: one LLM call, then deterministic conversion and
provenance lookup."""

import hashlib
from typing import Annotated

from pydantic import Field

from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder
from backend.app.domain.types import DomainModel
from backend.app.extraction.normalise import to_domain
from backend.app.extraction.provenance import locate
from backend.app.extraction.schema import ExtractedDocument
from backend.app.ingestion.models import ParsedDocument, Provenance, Table
from backend.app.llm.client import CacheKey, LLMClient, LLMUsage
from backend.app.llm.prompts import load_prompt

PROMPT_VERSION = "extract-v2"

AnyDocument = Annotated[PurchaseOrder | DeliveryNote | Invoice, Field(discriminator="doc_type")]


class ExtractionRecord(DomainModel):
    """Everything one extraction produced, kept apart from any later human correction.

    `raw` is exactly what the LLM returned. `document` is the converted domain document, or
    None when a field could not be parsed (`conversion_errors` says which).
    """

    source_sha256: str
    model: str
    prompt_version: str
    raw: ExtractedDocument
    document: AnyDocument | None
    conversion_errors: tuple[str, ...]
    provenance: dict[str, Provenance | None]
    usage: LLMUsage
    cached: bool
    seconds: float

    @property
    def unverified_fields(self) -> list[str]:
        return [path for path, prov in self.provenance.items() if prov is None]


def document_text(parsed: ParsedDocument) -> str:
    """The parsed document as plain text in reading order; tables as " | "-separated rows.

    Built from our own model rather than Docling's Markdown export, which HTML-escapes
    characters ("Harbour &amp; Hale") that would then be copied into the extraction.
    """
    parts: list[str] = []
    for element in parsed.elements:
        if isinstance(element, Table):
            parts.append("\n".join(" | ".join(row) for row in element.rows()))
        else:
            parts.append(element.text)
    return "\n\n".join(parts)


def llm_input(parsed: ParsedDocument) -> str:
    return f"<document>\n{document_text(parsed)}\n</document>"


def extract_document(
    parsed: ParsedDocument, llm: LLMClient, model: str, document_id: str
) -> ExtractionRecord:
    user = llm_input(parsed)
    result = llm.parse(
        model=model,
        system=load_prompt(PROMPT_VERSION),
        user=user,
        output_format=ExtractedDocument,
        cache_key=CacheKey(
            file_sha256=parsed.sha256,
            input_sha256=hashlib.sha256(user.encode()).hexdigest(),
            prompt_version=PROMPT_VERSION,
            model=model,
        ),
    )
    document, errors = to_domain(result.output, document_id)
    return ExtractionRecord(
        source_sha256=parsed.sha256,
        model=model,
        prompt_version=PROMPT_VERSION,
        raw=result.output,
        document=document,
        conversion_errors=errors,
        provenance=locate(parsed, result.output),
        usage=result.usage,
        cached=result.cached,
        seconds=result.seconds,
    )
