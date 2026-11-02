"""Dense retrieval over the owner's chunks with pgvector (cosine distance, HNSW index)."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import ChunkRow, DocumentRow
from backend.app.rag.embeddings import Embedder


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    document_id: str
    filename: str
    heading: str
    body: str
    page: int
    bbox: dict[str, Any]
    score: float  # cosine similarity, 1 = identical direction


def search(
    session: Session, owner_id: str, query: str, embedder: Embedder, k: int = 5
) -> list[Hit]:
    # owner_id filter first: retrieval must never cross tenants, whatever the query says.
    distance = ChunkRow.embedding.cosine_distance(embedder.embed_query(query))
    rows = session.execute(
        select(ChunkRow, DocumentRow.filename, distance.label("distance"))
        .join(DocumentRow, DocumentRow.id == ChunkRow.document_id)
        .where(ChunkRow.owner_id == owner_id)
        .order_by(distance)
        .limit(k)
    )
    return [
        Hit(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            heading=chunk.heading,
            body=chunk.body,
            page=chunk.page,
            bbox=chunk.bbox,
            score=1.0 - float(dist),
        )
        for chunk, filename, dist in rows
    ]
