"""From uploaded file to stored findings.

ingest_file       save the file, create the document row, queue one job (fast; the API calls it)
process_document  parse -> extract -> store -> revalidate (slow; the worker calls it)
apply_correction  record a person's fix to one field, rebuild the document, revalidate
revalidate_owner  re-run the rules over all of an owner's documents and update findings

Parser and LLM are passed in (`Services`) so tests run without Docling or the API.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.db.mapping import (
    ROW_CLASSES,
    DocumentRowType,
    document_from_row,
    document_to_row,
)
from backend.app.db.models import (
    CorrectionRow,
    DiscrepancyRow,
    DocumentRow,
    ExtractionRow,
    JobRow,
    ParseRow,
)
from backend.app.extraction.corrections import apply_corrections, get_field
from backend.app.extraction.extract import extract_document
from backend.app.extraction.normalise import to_domain
from backend.app.extraction.schema import ExtractedDocument
from backend.app.ingestion.models import ParsedDocument
from backend.app.jobs.queue import enqueue
from backend.app.llm.client import LLMClient
from backend.app.rag.chunking import metadata_context
from backend.app.rag.embeddings import Embedder
from backend.app.rag.index import index_document
from backend.app.storage import save_file
from backend.app.validation.models import IncompleteDocument
from backend.app.validation.rules import Document, validate

PROCESS_DOCUMENT = "process_document"


@dataclass(frozen=True)
class Services:
    parse: Callable[[Path], ParsedDocument]
    llm: LLMClient
    model: str
    storage_root: Path
    embedder: Embedder | None = None  # None: documents are not indexed for search


def ingest_file(
    session: Session, owner_id: str, filename: str, data: bytes, storage_root: Path
) -> tuple[DocumentRow, JobRow | None]:
    """Store an upload and queue it. The same file uploaded again by the same owner returns
    the existing document and queues nothing."""
    sha, path = save_file(storage_root, owner_id, data)
    existing = session.scalars(
        select(DocumentRow).where(DocumentRow.owner_id == owner_id, DocumentRow.sha256 == sha)
    ).first()
    if existing is not None:
        return existing, None
    document = DocumentRow(
        owner_id=owner_id, filename=filename, sha256=sha, storage_path=str(path), status="queued"
    )
    session.add(document)
    session.flush()  # assigns document.id
    job = enqueue(session, owner_id, PROCESS_DOCUMENT, {"document_id": document.id})
    session.flush()
    return document, job


def process_document(session: Session, document_id: str, owner_id: str, services: Services) -> None:
    document = session.get(DocumentRow, document_id)
    if document is None:
        raise LookupError(f"no document {document_id}")
    if document.owner_id != owner_id:
        raise PermissionError(f"document {document_id} does not belong to {owner_id}")
    if document.storage_path is None:
        raise ValueError(f"document {document_id} has no stored file")

    document.status = "processing"
    parsed = services.parse(Path(document.storage_path))
    session.add(
        ParseRow(
            document_id=document.id,
            owner_id=owner_id,
            parser=parsed.parser,
            ocr=parsed.ocr,
            data=parsed.model_dump(mode="json"),
        )
    )

    record = extract_document(parsed, services.llm, services.model, document.id)
    version = 1 + (
        session.scalar(
            select(func.max(ExtractionRow.version)).where(ExtractionRow.document_id == document.id)
        )
        or 0
    )
    session.add(
        ExtractionRow(
            document_id=document.id,
            owner_id=owner_id,
            version=version,
            model=record.model,
            prompt_version=record.prompt_version,
            raw=record.raw.model_dump(mode="json"),
            conversion_errors=list(record.conversion_errors),
            provenance={
                path: prov.model_dump(mode="json") if prov else None
                for path, prov in record.provenance.items()
            },
            input_tokens=record.usage.input_tokens,
            output_tokens=record.usage.output_tokens,
            cost_usd=record.usage.cost_usd,
            cached=record.cached,
        )
    )

    _store_result(session, document, record.raw)
    if services.embedder is not None:
        index_document(session, document, parsed, services.embedder, context=_context(record.raw))
    revalidate_owner(session, owner_id)


def apply_correction(
    session: Session, document_id: str, owner_id: str, field: str, new_value: str, author: str
) -> CorrectionRow:
    """Record a correction to the latest extraction, then rebuild the typed document from
    the raw extraction plus all its corrections. Raises LookupError for a document the
    owner does not have (so callers cannot tell "missing" from "someone else's") and
    InvalidFieldError for a path that is not a text field."""
    document = session.get(DocumentRow, document_id)
    if document is None or document.owner_id != owner_id:
        raise LookupError(f"no document {document_id}")
    extraction = _latest_extraction(session, document_id)
    if extraction is None:
        raise LookupError(f"document {document_id} has not been extracted yet")

    raw = ExtractedDocument.model_validate(extraction.raw)
    current = apply_corrections(raw, _corrections_for(session, extraction.id))
    old_value = get_field(current, field)
    corrected = apply_corrections(current, [(field, new_value)])  # validates path and value

    correction = CorrectionRow(
        document_id=document_id,
        owner_id=owner_id,
        extraction_id=extraction.id,
        field=field,
        old_value=old_value,
        new_value=new_value,
        author=author,
    )
    session.add(correction)
    _store_result(session, document, corrected)
    revalidate_owner(session, owner_id)
    return correction


def corrected_extraction(session: Session, extraction: ExtractionRow) -> ExtractedDocument:
    """The raw extraction with every recorded correction applied, in order."""
    raw = ExtractedDocument.model_validate(extraction.raw)
    return apply_corrections(raw, _corrections_for(session, extraction.id))


def _store_result(session: Session, document: DocumentRow, raw: ExtractedDocument) -> None:
    """Convert an (possibly corrected) extraction and store it as the document's typed row,
    replacing any earlier one. Unconvertible documents go to review."""
    for row_class in ROW_CLASSES.values():
        old = session.get(row_class, document.id)
        if old is not None:
            session.delete(old)
    session.flush()

    document.doc_type = raw.doc_type
    if raw.doc_type == "other":
        # Not a PO, delivery note or invoice (e.g. a supplier agreement): there are no
        # fields to check, so nothing to review; it is still searchable.
        document.status = "done"
        session.flush()
        return
    converted, _errors = to_domain(raw, document.id)
    if converted is not None:
        session.add(document_to_row(converted, document.owner_id))
        document.status = "done"
    else:
        document.status = "needs_review"
    session.flush()


def _context(raw: ExtractedDocument) -> str | None:
    """Context line for search chunks from the extraction; None lets the chunker use the
    document's own first lines (right for agreements and other text documents)."""
    if raw.doc_type == "other" or not raw.document_number:
        return None
    return metadata_context(
        raw.doc_type,
        raw.document_number,
        raw.supplier.name,
        raw.buyer.name,
        raw.issue_date,
        raw.po_reference,
    )


def _latest_extraction(session: Session, document_id: str) -> ExtractionRow | None:
    return session.scalars(
        select(ExtractionRow)
        .where(ExtractionRow.document_id == document_id)
        .order_by(ExtractionRow.version.desc())
        .limit(1)
    ).first()


def _corrections_for(session: Session, extraction_id: str) -> list[tuple[str, str]]:
    rows = session.scalars(
        select(CorrectionRow)
        .where(CorrectionRow.extraction_id == extraction_id)
        .order_by(CorrectionRow.seq)
    )
    return [(row.field, row.new_value) for row in rows]


def revalidate_owner(session: Session, owner_id: str) -> None:
    """Run the rules over all of the owner's documents and refresh the open findings.

    Findings a person resolved or dismissed are kept as they are and not raised again;
    every other open finding is replaced by the current result.
    """
    documents: list[Document] = []
    for row_class in ROW_CLASSES.values():
        for row in session.scalars(select(row_class).where(row_class.owner_id == owner_id)):
            assert isinstance(row, DocumentRowType)
            documents.append(document_from_row(row))
    # A comprehension, not dict(result): SQLAlchemy results have .keys(), so dict() would
    # treat them as a mapping.
    received_order = {
        document_id: seq
        for document_id, seq in session.execute(
            select(DocumentRow.id, DocumentRow.received_seq).where(DocumentRow.owner_id == owner_id)
        )
    }

    report = validate(documents, _incomplete(session, owner_id), received_order)

    decided = {
        (r.document_id, r.rule, r.field)
        for r in session.scalars(
            select(DiscrepancyRow).where(
                DiscrepancyRow.owner_id == owner_id, DiscrepancyRow.status != "open"
            )
        )
    }
    session.execute(
        delete(DiscrepancyRow).where(
            DiscrepancyRow.owner_id == owner_id, DiscrepancyRow.status == "open"
        )
    )
    for finding in report.discrepancies:
        if (finding.document_id, finding.rule, finding.field) in decided:
            continue
        session.add(
            DiscrepancyRow(
                owner_id=owner_id,
                document_id=finding.document_id,
                rule=finding.rule,
                type=finding.type.value,
                field=finding.field,
                expected=finding.expected,
                actual=finding.actual,
                related_document_id=finding.related_document_id,
                amount_impact=finding.amount_impact,
                message=finding.message,
            )
        )
    session.flush()


def _incomplete(session: Session, owner_id: str) -> list[IncompleteDocument]:
    """Documents under review, described by their latest extraction."""
    pending = []
    for document in session.scalars(
        select(DocumentRow).where(
            DocumentRow.owner_id == owner_id, DocumentRow.status == "needs_review"
        )
    ):
        latest = _latest_extraction(session, document.id)
        if latest is None:
            continue
        raw = corrected_extraction(session, latest)
        own = raw.doc_type == "purchase_order"
        pending.append(
            IncompleteDocument(
                document_id=document.id,
                doc_type=raw.doc_type,
                po_number=raw.document_number if own else raw.po_reference,
            )
        )
    return pending
