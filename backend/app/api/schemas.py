"""Request and response bodies of the HTTP API. Separate from the table rows on purpose: the
API shows what a client needs, not how it is stored."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DocumentSummary(_Out):
    id: str
    filename: str
    status: str
    doc_type: str | None
    created_at: datetime


class UploadResult(DocumentSummary):
    job_id: str | None  # None when the file had already been uploaded


class ExtractionOut(_Out):
    id: str
    version: int
    model: str
    prompt_version: str
    raw: dict[str, Any]
    conversion_errors: list[str]
    provenance: dict[str, Any]
    cost_usd: Decimal
    cached: bool
    created_at: datetime


class CorrectionIn(BaseModel):
    field: str = Field(examples=["lines[1].quantity"])
    new_value: str
    author: str = Field(min_length=1, max_length=255)


class CorrectionOut(_Out):
    id: str
    field: str
    old_value: str
    new_value: str
    author: str
    created_at: datetime


class DiscrepancyOut(_Out):
    id: str
    document_id: str
    filename: str
    rule: str
    type: str
    field: str | None
    expected: str | None
    actual: str | None
    related_document_id: str | None
    amount_impact: Decimal | None
    message: str
    status: str
    created_at: datetime


class DiscrepancyUpdate(BaseModel):
    status: Literal["open", "resolved", "dismissed"]


class DocumentDetail(DocumentSummary):
    document: dict[str, Any] | None  # the typed document (after corrections), if complete
    extraction: ExtractionOut | None  # the latest extraction, exactly as the model returned it
    corrections: list[CorrectionOut]
    discrepancies: list[DiscrepancyOut]


class JobOut(_Out):
    id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None
    created_at: datetime


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class CitationOut(BaseModel):
    number: int
    document_id: str
    filename: str
    heading: str
    page: int
    bbox: dict[str, Any]
    text: str


class AskOut(BaseModel):
    question: str
    intent: str
    answer: str
    answerable: bool
    citations: list[CitationOut]
    sources: list[CitationOut]
    data: dict[str, Any]
    cost_usd: Decimal
    warnings: list[str]
