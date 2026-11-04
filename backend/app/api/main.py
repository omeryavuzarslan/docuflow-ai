"""The HTTP API.

    uv run --env-file .env uvicorn backend.app.api.main:app --reload
    then open http://localhost:8000/docs

Every request names its owner in the `X-Owner-Id` header and only ever sees that owner's
data. A document of another owner answers 404, never 403, so ids cannot be probed.
(Real authentication replaces the header at the deployment step.)

Uploads are only stored and queued here; the worker does the slow processing.
"""

import os
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.schemas import (
    AskIn,
    AskOut,
    CorrectionIn,
    CorrectionOut,
    DiscrepancyOut,
    DiscrepancyUpdate,
    DocumentDetail,
    DocumentSummary,
    ExtractionOut,
    JobOut,
    UploadResult,
)
from backend.app.db.mapping import ROW_CLASSES, DocumentRowType, document_from_row
from backend.app.db.models import (
    CorrectionRow,
    DeliveryNoteRow,
    DiscrepancyRow,
    DocumentRow,
    ExtractionRow,
    InvoiceRow,
    JobRow,
    PurchaseOrderRow,
)
from backend.app.db.session import make_engine, make_session_factory
from backend.app.extraction.corrections import InvalidFieldError
from backend.app.llm.client import LLMClient
from backend.app.pipeline.process import apply_correction, ingest_file, revalidate_owner
from backend.app.query.answer import answer_question
from backend.app.rag.embeddings import Embedder, LocalEmbedder

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_OWNER = re.compile(r"[A-Za-z0-9_-]{1,64}")


def create_app(
    session_factory: sessionmaker[Session] | None = None,
    storage_root: Path | None = None,
    llm: LLMClient | None = None,
    embedder: Embedder | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own session factory, storage, LLM client and
    embedder; the server builds them from DATABASE_URL, STORAGE_DIR and LLM_CACHE_DIR."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.session_factory = session_factory or make_session_factory(make_engine())
        app.state.storage_root = storage_root or Path(os.environ.get("STORAGE_DIR", "storage"))
        app.state.llm = llm or LLMClient(Path(os.environ.get("LLM_CACHE_DIR", ".cache/llm")))
        app.state.embedder = embedder or LocalEmbedder()  # loads the model on first use
        app.state.model = os.environ.get("ANSWER_MODEL", "claude-haiku-5-5")
        yield

    app = FastAPI(
        title="DocuFlow AI",
        summary="Invoices, purchase orders and delivery notes: extraction and discrepancy checks.",
        lifespan=lifespan,
    )
    _routes(app)
    return app


# --- dependencies --------------------------------------------------------------------


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_owner(x_owner_id: Annotated[str | None, Header()] = None) -> str:
    if x_owner_id is None or not _OWNER.fullmatch(x_owner_id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid X-Owner-Id header")
    return x_owner_id


SessionDep = Annotated[Session, Depends(get_session)]
OwnerDep = Annotated[str, Depends(get_owner)]


def _owned_document(session: Session, owner: str, document_id: str) -> DocumentRow:
    document = session.get(DocumentRow, document_id)
    if document is None or document.owner_id != owner:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return document


def _discrepancies(session: Session, owner: str, **filters: str | None) -> list[DiscrepancyOut]:
    query = (
        select(DiscrepancyRow, DocumentRow.filename)
        .join(DocumentRow, DocumentRow.id == DiscrepancyRow.document_id)
        .where(DiscrepancyRow.owner_id == owner)
        .order_by(DocumentRow.filename, DiscrepancyRow.rule, DiscrepancyRow.field)
    )
    for column, value in filters.items():
        if value is not None:
            query = query.where(getattr(DiscrepancyRow, column) == value)
    return [
        DiscrepancyOut.model_validate({**_columns(row), "filename": filename})
        for row, filename in session.execute(query)
    ]


def _summary_fields(row: DocumentRow) -> dict[str, object]:
    return {f: getattr(row, f) for f in ("id", "filename", "status", "doc_type", "created_at")}


def _document_facts(session: Session, owner: str, ids: list[str]) -> dict[str, dict[str, object]]:
    """Number, supplier and amount per document, read from the typed tables in three
    queries (not one per row)."""
    facts: dict[str, dict[str, object]] = {}
    if not ids:
        return facts
    for row in session.scalars(
        select(InvoiceRow).where(InvoiceRow.owner_id == owner, InvoiceRow.document_id.in_(ids))
    ):
        facts[row.document_id] = {
            "number": row.invoice_number,
            "counterparty": row.supplier_name,
            "amount": row.gross_total,
        }
    for po in session.scalars(
        select(PurchaseOrderRow).where(
            PurchaseOrderRow.owner_id == owner, PurchaseOrderRow.document_id.in_(ids)
        )
    ):
        facts[po.document_id] = {
            "number": po.po_number,
            "counterparty": po.supplier_name,
            "amount": po.net_total,
        }
    for dn in session.scalars(
        select(DeliveryNoteRow).where(
            DeliveryNoteRow.owner_id == owner, DeliveryNoteRow.document_id.in_(ids)
        )
    ):
        facts[dn.document_id] = {"number": dn.dn_number, "counterparty": dn.supplier_name}
    return facts


def _columns(row: DiscrepancyRow) -> dict[str, object]:
    return {c.key: getattr(row, c.key) for c in DiscrepancyRow.__table__.columns}


# --- routes --------------------------------------------------------------------------


def _routes(app: FastAPI) -> None:
    @app.get("/health")
    def health(session: SessionDep) -> dict[str, str]:
        session.execute(text("select 1"))
        return {"status": "ok", "database": "ok"}

    @app.post("/documents", response_model=UploadResult, status_code=status.HTTP_202_ACCEPTED)
    def upload(
        request: Request,
        response: Response,
        session: SessionDep,
        owner: OwnerDep,
        file: Annotated[
            UploadFile, File(description="A PDF invoice, purchase order or delivery note")
        ],
    ) -> UploadResult:
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file larger than 20 MB")
        if not data.startswith(b"%PDF"):  # check the bytes, not the name or declared type
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only PDF files are accepted"
            )
        document, job = ingest_file(
            session, owner, file.filename or "upload.pdf", data, request.app.state.storage_root
        )
        session.commit()
        if job is None:
            response.status_code = status.HTTP_200_OK  # already uploaded: nothing new queued
        return UploadResult.model_validate(
            {
                **DocumentSummary.model_validate(document).model_dump(),
                "job_id": job.id if job else None,
            }
        )

    @app.get("/documents", response_model=list[DocumentSummary])
    def list_documents(
        session: SessionDep,
        owner: OwnerDep,
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[DocumentSummary]:
        query = select(DocumentRow).where(DocumentRow.owner_id == owner)
        if status_filter is not None:
            query = query.where(DocumentRow.status == status_filter)
        query = query.order_by(DocumentRow.received_seq).limit(limit).offset(offset)
        rows = list(session.scalars(query))
        facts = _document_facts(session, owner, [r.id for r in rows])
        return [
            DocumentSummary.model_validate({**_summary_fields(r), **facts.get(r.id, {})})
            for r in rows
        ]

    @app.get("/documents/{document_id}", response_model=DocumentDetail)
    def get_document(document_id: str, session: SessionDep, owner: OwnerDep) -> DocumentDetail:
        document = _owned_document(session, owner, document_id)
        typed = None
        row_class = ROW_CLASSES.get(document.doc_type or "")
        if row_class is not None:
            row = session.get(row_class, document_id)
            if isinstance(row, DocumentRowType):
                typed = document_from_row(row).model_dump(mode="json")
        extraction = session.scalars(
            select(ExtractionRow)
            .where(ExtractionRow.document_id == document_id)
            .order_by(ExtractionRow.version.desc())
            .limit(1)
        ).first()
        corrections = (
            session.scalars(
                select(CorrectionRow)
                .where(CorrectionRow.extraction_id == extraction.id)
                .order_by(CorrectionRow.seq)
            ).all()
            if extraction is not None
            else []
        )
        return DocumentDetail.model_validate(
            {
                **_summary_fields(document),
                **_document_facts(session, owner, [document_id]).get(document_id, {}),
                "document": typed,
                "extraction": ExtractionOut.model_validate(extraction) if extraction else None,
                "corrections": [CorrectionOut.model_validate(c) for c in corrections],
                "discrepancies": _discrepancies(session, owner, document_id=document_id),
            }
        )

    @app.get("/documents/{document_id}/file", response_class=Response)
    def download(document_id: str, session: SessionDep, owner: OwnerDep) -> Response:
        document = _owned_document(session, owner, document_id)
        if document.storage_path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "file not stored")
        return Response(Path(document.storage_path).read_bytes(), media_type="application/pdf")

    @app.post(
        "/documents/{document_id}/corrections",
        response_model=CorrectionOut,
        status_code=status.HTTP_201_CREATED,
    )
    def correct(
        document_id: str, body: CorrectionIn, session: SessionDep, owner: OwnerDep
    ) -> CorrectionRow:
        try:
            correction = apply_correction(
                session, document_id, owner, body.field, body.new_value, body.author
            )
        except LookupError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found") from exc
        except InvalidFieldError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        session.commit()
        return correction

    @app.get("/discrepancies", response_model=list[DiscrepancyOut])
    def list_discrepancies(
        session: SessionDep,
        owner: OwnerDep,
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        document_id: str | None = None,
    ) -> list[DiscrepancyOut]:
        return _discrepancies(session, owner, status=status_filter, document_id=document_id)

    @app.patch("/discrepancies/{discrepancy_id}", response_model=DiscrepancyOut)
    def update_discrepancy(
        discrepancy_id: str, body: DiscrepancyUpdate, session: SessionDep, owner: OwnerDep
    ) -> DiscrepancyOut:
        finding = session.get(DiscrepancyRow, discrepancy_id)
        if finding is None or finding.owner_id != owner:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "discrepancy not found")
        finding.status = body.status
        if body.status == "open":
            revalidate_owner(session, owner)  # reopening: let the rules decide again
        session.commit()
        result = next((d for d in _discrepancies(session, owner) if d.id == discrepancy_id), None)
        if result is None:  # reopened, and the rules no longer find it
            raise HTTPException(status.HTTP_404_NOT_FOUND, "discrepancy no longer applies")
        return result

    @app.post("/ask", response_model=AskOut)
    def ask(body: AskIn, request: Request, session: SessionDep, owner: OwnerDep) -> AskOut:
        """Answer a question about the owner's documents. Numbers come from SQL; text
        answers cite the passages they rely on (file, page and box)."""
        result = answer_question(
            session,
            owner,
            body.question,
            request.app.state.llm,
            request.app.state.embedder,
            request.app.state.model,
            date.today(),
        )
        return AskOut.model_validate(asdict(result))

    @app.get("/jobs/{job_id}", response_model=JobOut)
    def get_job(job_id: str, session: SessionDep, owner: OwnerDep) -> JobRow:
        job = session.get(JobRow, job_id)
        if job is None or job.owner_id != owner:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
        return job


app = create_app()
