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
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from backend.app.db.models import DocumentRow
from backend.app.db.session import make_engine, make_session_factory
from backend.app.domain.agreements import SupplierAgreement
from backend.app.domain.document_set import DocumentSet
from backend.app.rag.chunking import Strategy
from backend.app.rag.embeddings import LocalEmbedder
from backend.app.rag.index import index_document
from backend.app.rag.retrieve import hybrid_search, keyword_search, search
from backend.app.validation.rules import Document
from eval.runners.extraction_eval import load_parsed
from eval.runners.retrieval_questions import (
    Question,
    build_lookup_questions,
    build_questions,
    first_relevant_rank,
    mean_reciprocal_rank,
    recall_at,
)

STRATEGIES: tuple[Strategy, ...] = ("structure", "structure_no_context", "fixed")
MODES = ("dense", "keyword", "hybrid")
K = 10


def _sets(dataset: Path) -> list[DocumentSet]:
    manifest = json.loads((dataset / "manifest.json").read_text())
    return [
        DocumentSet.model_validate_json((dataset / e["set_id"] / "ground_truth.json").read_bytes())
        for e in manifest["sets"]
    ]


def _contexts(dataset: Path) -> dict[str, str]:
    """The context line the pipeline builds from a (correct) extraction, per document. On
    digital PDFs extraction is exact (docs/experiments.md), so the ground truth stands in."""
    from backend.app.rag.chunking import metadata_context
    from data_generator.render import format_date

    contexts: dict[str, str] = {}
    for doc_set in _sets(dataset):
        po, dn = doc_set.purchase_order, doc_set.delivery_note
        entries: list[tuple[Document, str, date, str]] = [
            (po, po.po_number, po.issue_date, ""),
            (dn, dn.dn_number, dn.delivery_date, dn.po_number),
        ]
        entries += [(i, i.invoice_number, i.issue_date, i.po_number) for i in doc_set.invoices]
        for doc, number, issued, ref in entries:
            contexts[doc.document_id] = metadata_context(
                doc.doc_type, number, doc.supplier.name, doc.buyer.name, format_date(issued), ref
            )
    return contexts


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


def _doc_type(document_id: str) -> str:
    if document_id.startswith("agreement"):
        return "other"
    if document_id.endswith("-po"):
        return "purchase_order"
    if document_id.endswith("-dn"):
        return "delivery_note"
    return "invoice"


def index_corpus(
    session: Session,
    strategy: Strategy,
    files: list[tuple[str, Path]],
    embedder: LocalEmbedder,
    contexts: dict[str, str],
) -> tuple[str, int]:
    """Index every file under a per-strategy owner; returns (owner, number of chunks)."""
    owner = f"retrieval-eval-{strategy}"
    session.execute(delete(DocumentRow).where(DocumentRow.owner_id == owner))
    chunks = 0
    for document_id, path in files:
        row = DocumentRow(
            id=f"{strategy}:{document_id}",
            owner_id=owner,
            filename=path.name,
            sha256=f"{strategy}:{document_id}"[:64],
            status="done",
            doc_type=_doc_type(document_id),
        )
        session.add(row)
        session.flush()
        chunks += index_document(
            session, row, load_parsed(path), embedder, strategy, contexts.get(document_id)
        )
    session.commit()
    return owner, chunks


def evaluate(
    session: Session,
    owner: str,
    prefix: str,
    mode: str,
    questions: list[Question],
    embedder: LocalEmbedder,
    filtered: bool = False,
) -> dict[str, Any]:
    """`filtered`: search only documents of the answer's type, i.e. what a perfect query
    router would do. An upper bound for the router built in step 7b."""
    ranks: list[int | None] = []
    by_kind: dict[str, list[int | None]] = defaultdict(list)
    latencies = []
    misses = []
    for q in questions:
        start = time.perf_counter()
        types = [q.doc_type] if filtered else None
        if mode == "dense":
            hits = search(session, owner, q.question, embedder, K, types)
        elif mode == "keyword":
            hits = keyword_search(session, owner, q.question, K, types)
        else:
            hits = hybrid_search(session, owner, q.question, embedder, K, types)
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
        "mode": mode + (" + type filter" if filtered else ""),
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
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    parser.add_argument(
        "--approximate",
        action="store_true",
        help="use the HNSW index as production does (results vary slightly between rebuilds)",
    )
    parser.add_argument(
        "--context",
        choices=["metadata", "first-lines"],
        default="metadata",
        help="context line for POs/DNs/invoices: from extracted fields, or the page's first lines",
    )
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args(argv)

    files, agreements = _corpus(args.dataset)
    groups = {
        "clauses": build_questions(agreements, seed=args.seed),
        "lookups": build_lookup_questions(agreements, _sets(args.dataset), seed=args.seed),
    }
    contexts = _contexts(args.dataset) if args.context == "metadata" else {}
    embedder = LocalEmbedder()
    factory = make_session_factory(make_engine())
    results = []
    with factory() as session:
        if not args.approximate:
            # Exact nearest neighbours: HNSW is approximate and its graph has random levels,
            # so rebuilt indexes rank a few ties differently. The eval measures the ranking
            # itself; at ~500 chunks an exact scan costs only milliseconds.
            session.execute(text("SET enable_indexscan = off"))
        for strategy in args.strategies:
            print(f"indexing: {strategy}", flush=True)
            owner, chunks = index_corpus(session, strategy, files, embedder, contexts)
            # The chunking comparison is dense-only (as in v1); modes are compared on the
            # default "structure" chunks.
            modes = args.modes if strategy == "structure" else ["dense"]
            runs = [(m, False) for m in modes]
            if strategy == "structure" and "hybrid" in modes:
                runs.append(("hybrid", True))
            for mode, filtered in runs:
                for group, questions in groups.items():
                    result = evaluate(
                        session, owner, f"{strategy}:", mode, questions, embedder, filtered
                    )
                    results.append(
                        {"strategy": strategy, "group": group, "chunks": chunks, **result}
                    )

    report = {
        "dataset": str(args.dataset),
        "embedding_model": embedder.model_name,
        "context": args.context,
        "nearest_neighbours": "approximate (HNSW)" if args.approximate else "exact",
        "documents": len(files),
        "questions": {group: len(qs) for group, qs in groups.items()},
        "k": K,
        "results": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"retrieval-{args.dataset.name}-{args.context}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    sizes = ", ".join(f"{len(qs)} {g}" for g, qs in groups.items())
    print(f"\n{len(files)} documents, questions: {sizes}; wrote {out}")
    print("| strategy | mode | questions | Recall@1 | Recall@5 | Recall@10 | MRR | median ms |")
    print("|---|---|---|---|---|---|---|---|")
    for r in results:
        print(
            f"| {r['strategy']} | {r['mode']} | {r['group']} | {r['recall@1']:.1%} "
            f"| {r['recall@5']:.1%} | {r['recall@10']:.1%} | {r['mrr']:.3f} "
            f"| {r['median_search_ms']} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
