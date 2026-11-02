from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.db.models import ChunkRow, DocumentRow
from backend.app.ingestion.models import ParsedDocument
from backend.app.rag.chunking import Strategy, chunk
from backend.app.rag.embeddings import Embedder


def index_document(
    session: Session,
    document: DocumentRow,
    parsed: ParsedDocument,
    embedder: Embedder,
    strategy: Strategy = "structure",
) -> int:
    """(Re)build a document's chunks and vectors; returns how many chunks were stored."""
    session.execute(delete(ChunkRow).where(ChunkRow.document_id == document.id))
    chunks = chunk(parsed, strategy)
    vectors = embedder.embed_documents([c.text for c in chunks]) if chunks else []
    for c, vector in zip(chunks, vectors, strict=True):
        session.add(
            ChunkRow(
                owner_id=document.owner_id,
                document_id=document.id,
                ordinal=c.ordinal,
                kind=c.kind,
                heading=c.heading,
                body=c.body,
                text=c.text,
                page=c.page,
                bbox=c.bbox.model_dump(mode="json"),
                embedding=vector,
                embedding_model=embedder.model_name,
            )
        )
    session.flush()
    return len(chunks)
