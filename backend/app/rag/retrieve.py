"""Retrieval over the owner's chunks.

dense    pgvector cosine similarity on the embeddings (meaning: "payment terms" ~ "days to pay")
keyword  Postgres full-text search (exact terms: SKUs, invoice numbers, amounts)
hybrid   both lists fused with Reciprocal Rank Fusion: score = sum of 1 / (60 + rank), plus
         a third list when the question names codes: chunks containing those exact codes.
         Postgres ranking has no IDF (rare terms weigh no more than common ones), so without
         it one decisive "OF-1004" loses to a chunk that repeats both company names.

Codes such as "INV-2026-00379" or "OF-1001" are split by Postgres's English parser into
fragments ("inv", "-2026", "-00379") that match far too much. Chunks therefore also store each
code without hyphens ("INV202600379") as one extra word, and queries get the same treatment.

Every query is filtered by owner first; `doc_types` narrows it further (used by the router).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, Text, cast, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.orm import Session

from backend.app.db.models import ChunkRow, DocumentRow
from backend.app.rag.embeddings import Embedder

RRF_K = 60  # the constant from the original RRF paper; dampens the weight of rank 1
CANDIDATES = 50  # results taken from each list before fusing

_CODE = re.compile(r"\b[A-Za-z]{1,5}(?:-[A-Za-z0-9]+)+\b")


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    document_id: str
    filename: str
    heading: str
    body: str  # the passage itself, for display
    text: str  # context line + heading + body: what was embedded, and what an LLM needs
    page: int
    bbox: dict[str, Any]
    score: float  # dense: cosine similarity; keyword: ts_rank; hybrid: RRF score


def with_code_tokens(text: str) -> str:
    """Append every hyphenated code once more without hyphens, as a single searchable word."""
    codes = {m.group(0).replace("-", "").upper() for m in _CODE.finditer(text)}
    return f"{text} {' '.join(sorted(codes))}" if codes else text


def _scoped(owner_id: str, doc_types: Sequence[str] | None, *columns: Any) -> Select[Any]:
    query = (
        select(ChunkRow, DocumentRow.filename, *columns)
        .join(DocumentRow, DocumentRow.id == ChunkRow.document_id)
        .where(ChunkRow.owner_id == owner_id)
    )
    if doc_types:
        query = query.where(DocumentRow.doc_type.in_(doc_types))
    return query


def _hit(chunk: ChunkRow, filename: str, score: float) -> Hit:
    return Hit(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        filename=filename,
        heading=chunk.heading,
        body=chunk.body,
        text=chunk.text,
        page=chunk.page,
        bbox=chunk.bbox,
        score=score,
    )


def search(
    session: Session,
    owner_id: str,
    query: str,
    embedder: Embedder,
    k: int = 5,
    doc_types: Sequence[str] | None = None,
) -> list[Hit]:
    """Dense retrieval (pgvector, cosine)."""
    distance = ChunkRow.embedding.cosine_distance(embedder.embed_query(query))
    rows = session.execute(
        _scoped(owner_id, doc_types, distance.label("distance"))
        .order_by(distance, ChunkRow.document_id, ChunkRow.ordinal)  # stable ties
        .limit(k)
    )
    return [_hit(chunk, filename, 1.0 - float(dist)) for chunk, filename, dist in rows]


def keyword_search(
    session: Session,
    owner_id: str,
    query: str,
    k: int = 5,
    doc_types: Sequence[str] | None = None,
) -> list[Hit]:
    """Full-text search. Terms are OR-ed: a question's words rarely all occur in one chunk,
    and ts_rank_cd ranks chunks that contain more of them (closer together) higher."""
    and_query = func.plainto_tsquery("english", with_code_tokens(query))
    or_query = cast(func.replace(cast(and_query, Text), "&", "|"), TSQUERY)
    rank = func.ts_rank_cd(ChunkRow.tsv, or_query)
    rows = session.execute(
        _scoped(owner_id, doc_types, rank.label("rank"))
        .where(ChunkRow.tsv.op("@@")(or_query))
        .order_by(rank.desc(), ChunkRow.document_id, ChunkRow.ordinal)
        .limit(k)
    )
    return [_hit(chunk, filename, float(score)) for chunk, filename, score in rows]


def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion of ranked id lists; best first. Ties keep first-seen order."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: -pair[1])


def code_search(
    session: Session,
    owner_id: str,
    query: str,
    k: int = 5,
    doc_types: Sequence[str] | None = None,
) -> list[Hit]:
    """Chunks containing the exact codes named in the query (hyphens ignored); [] if none."""
    codes = sorted({m.group(0).replace("-", "").lower() for m in _CODE.finditer(query)})
    if not codes:
        return []
    code_query = func.to_tsquery("simple", " | ".join(codes))
    rank = func.ts_rank_cd(func.to_tsvector("simple", ChunkRow.search_text), code_query)
    rows = session.execute(
        _scoped(owner_id, doc_types, rank.label("rank"))
        .where(func.to_tsvector("simple", ChunkRow.search_text).op("@@")(code_query))
        .order_by(rank.desc(), ChunkRow.document_id, ChunkRow.ordinal)
        .limit(k)
    )
    return [_hit(chunk, filename, float(score)) for chunk, filename, score in rows]


def hybrid_search(
    session: Session,
    owner_id: str,
    query: str,
    embedder: Embedder,
    k: int = 5,
    doc_types: Sequence[str] | None = None,
) -> list[Hit]:
    dense = search(session, owner_id, query, embedder, CANDIDATES, doc_types)
    keyword = keyword_search(session, owner_id, query, CANDIDATES, doc_types)
    codes = code_search(session, owner_id, query, CANDIDATES, doc_types)
    by_id = {h.chunk_id: h for h in (*dense, *keyword, *codes)}
    fused = rrf_fuse(
        [[h.chunk_id for h in ranking] for ranking in (dense, keyword, codes) if ranking]
    )
    return [Hit(**{**by_id[chunk_id].__dict__, "score": score}) for chunk_id, score in fused[:k]]
