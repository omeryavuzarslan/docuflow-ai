"""Retrieval evaluation: Recall@K and MRR per chunking strategy.

Corpus: the 15 supplier agreements plus every digital PO, delivery note and invoice of the
dataset (as distractors), parsed with Docling exactly like uploads. Each strategy is indexed
under its own owner in the development database and queried through the real `search`
(pgvector), with the local embedding model. Free: no API calls.

    uv run --env-file .env python -m eval.runners.retrieval_eval \\
        --dataset data_generator/output/seed-42
"""

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.db.models import DocumentRow
from backend.app.db.session import make_engine, make_session_factory
from backend.app.domain.agreements import SupplierAgreement
from backend.app.rag.chunking import Strategy
from backend.app.rag.embeddings import LocalEmbedder
from backend.app.rag.index import index_document
from backend.app.rag.retrieve import search
from eval.runners.extraction_eval import load_parsed
from eval.runners.retrieval_questions import (
    build_questions,
    first_relevant_rank,
    mean_reciprocal_rank,
    recall_at,
)

STRATEGIES: tuple[Strategy, ...] = ("structure", "structure_no_context", "fixed")
K = 10


def _corpus(dataset: Path) -> tuple[list[tuple[str, Path]], tuple[SupplierAgreement, ...]]:
    manifest = json.loads((dataset / "manifest.json").read_text())
    files = [(entry["document_id"], dataset / entry["file"]) for entry in manifest["agreements"]]
    agreements = tuple(
        SupplierAgreement.model_validate_json((dataset / e["json"]).read_bytes())
        for e in manifest["agreements"]
    )
    for entry in manifest["sets"]:
        for document_id, name in entry["files"].items():
            files.append((document_id, dataset / entry["set_id"] / name))
    return files, agreements


def run_strategy(
    session: Session,
    strategy: Strategy,
    files: list[tuple[str, Path]],
    questions: list[Any],
    embedder: LocalEmbedder,
) -> dict[str, Any]:
    owner = f"retrieval-eval-{strategy}"
    prefix = f"{strategy}:"
    # Start from a clean slate for this owner (chunks go with their documents).
    session.execute(delete(DocumentRow).where(DocumentRow.owner_id == owner))
    chunks = 0
    for document_id, path in files:
        row = DocumentRow(
            id=prefix + document_id,
            owner_id=owner,
            filename=path.name,
            sha256=f"{strategy}:{document_id}"[:64],
            status="done",
        )
        session.add(row)
        session.flush()
        chunks += index_document(session, row, load_parsed(path), embedder, strategy=strategy)
    session.commit()

    ranks: list[int | None] = []
    by_kind: dict[str, list[int | None]] = defaultdict(list)
    latencies = []
    misses = []
    for q in questions:
        start = time.perf_counter()
        hits = search(session, owner, q.question, embedder, k=K)
        latencies.append((time.perf_counter() - start) * 1000)
        rank = first_relevant_rank(q, [(h.document_id.removeprefix(prefix), h.body) for h in hits])
        ranks.append(rank)
        by_kind[q.kind].append(rank)
        if rank is None or rank > 1:
            top = hits[0] if hits else None
            misses.append(
                {
                    "id": q.id,
                    "rank": rank,
                    "question": q.question,
                    "top_document": top.document_id.removeprefix(prefix) if top else None,
                    "top_heading": top.heading if top else None,
                }
            )
    return {
        "strategy": strategy,
        "chunks": chunks,
        "questions": len(questions),
        "recall@1": round(recall_at(ranks, 1), 4),
        "recall@5": round(recall_at(ranks, 5), 4),
        "recall@10": round(recall_at(ranks, 10), 4),
        "mrr": round(mean_reciprocal_rank(ranks), 4),
        "median_search_ms": round(statistics.median(latencies), 1),
        "by_kind_recall@1": {k: round(recall_at(v, 1), 3) for k, v in sorted(by_kind.items())},
        "not_first": misses,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.runners.retrieval_eval")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42, help="question sampling seed")
    parser.add_argument("--strategies", nargs="+", default=list(STRATEGIES), choices=STRATEGIES)
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args(argv)

    files, agreements = _corpus(args.dataset)
    questions = build_questions(agreements, seed=args.seed)
    embedder = LocalEmbedder()
    factory = make_session_factory(make_engine())
    results = []
    with factory() as session:
        for strategy in args.strategies:
            print(f"indexing and querying: {strategy}", flush=True)
            results.append(run_strategy(session, strategy, files, questions, embedder))

    report = {
        "dataset": str(args.dataset),
        "embedding_model": embedder.model_name,
        "documents": len(files),
        "questions": len(questions),
        "k": K,
        "results": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"retrieval-{args.dataset.name}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\n{len(files)} documents, {len(questions)} questions; wrote {out}")
    print("| strategy | chunks | Recall@1 | Recall@5 | Recall@10 | MRR | median search ms |")
    print("|---|---|---|---|---|---|---|")
    for r in results:
        print(
            f"| {r['strategy']} | {r['chunks']} | {r['recall@1']:.1%} | {r['recall@5']:.1%} "
            f"| {r['recall@10']:.1%} | {r['mrr']:.3f} | {r['median_search_ms']} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
