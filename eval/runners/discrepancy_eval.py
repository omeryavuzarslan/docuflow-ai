"""Discrepancy evaluation: precision and recall of the rule engine.

Two modes:

  truth      Rules on ground-truth documents (generated in memory, free). Measures the rules
             alone, on many sets.
  extracted  The full pipeline: PDF -> Docling -> Claude -> rules, using cached LLM responses
             only (no API calls, so free). Measures what reading errors do to detection.
             Documents whose extraction could not be converted are counted as "sent to
             review" instead of being checked.

A finding is a true positive when (document_id, type) matches an injected error.

    uv run python -m eval.runners.discrepancy_eval truth --seed 7 --sets 100
    uv run python -m eval.runners.discrepancy_eval extracted \\
        --dataset data_generator/output/seed-42 --model claude-haiku-5-5
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backend.app.domain.document_set import DocumentSet
from backend.app.extraction.extract import PROMPT_VERSION, extract_document
from backend.app.llm.client import LLMClient, LLMError
from backend.app.validation.models import IncompleteDocument
from backend.app.validation.rules import Document, validate
from data_generator.generate import generate
from eval.runners.extraction_eval import CACHE, load_parsed

Key = tuple[str, str]  # (document_id, type)


def score(truth: set[Key], predicted: list[Key]) -> dict[str, Any]:
    """Overall and per-type precision/recall. Duplicate predictions count as false positives."""
    counts = Counter(predicted)
    tp = {k for k in counts if k in truth}
    fp = [k for k in predicted if k not in truth] + [
        k for k, n in counts.items() if k in truth and n > 1
    ]
    fn = sorted(truth - tp)

    def ratio(a: int, b: int) -> float:
        return round(a / b, 4) if b else 1.0

    per_type: dict[str, dict[str, Any]] = {}
    for kind in sorted({k[1] for k in truth} | {k[1] for k in predicted}):
        t = {k for k in truth if k[1] == kind}
        p = [k for k in predicted if k[1] == kind]
        hits = len({k for k in p if k in t})
        per_type[kind] = {
            "injected": len(t),
            "found": hits,
            "false_alarms": len(p) - hits,
            "recall": ratio(hits, len(t)),
            "precision": ratio(hits, len(p)),
        }
    return {
        "injected": len(truth),
        "predicted": len(predicted),
        "true_positives": len(tp),
        "precision": ratio(len(tp), len(predicted)),
        "recall": ratio(len(tp), len(truth)),
        "false_positives": [list(k) for k in fp],
        "missed": [list(k) for k in fn],
        "per_type": per_type,
    }


def _documents(sets: Sequence[DocumentSet]) -> list[Document]:
    docs: list[Document] = []
    for s in sets:
        docs += [s.purchase_order, s.delivery_note, *s.invoices]
    return docs


def _truth(sets: Sequence[DocumentSet]) -> set[Key]:
    return {(e.document_id, e.type.value) for s in sets for e in s.errors}


def run_truth(seed: int, n_sets: int) -> dict[str, Any]:
    sets = generate(seed, n_sets)
    report = validate(_documents(sets))
    result = score(_truth(sets), [(d.document_id, d.type.value) for d in report.discrepancies])
    clean_ids = {d.document_id for s in sets if s.is_clean for d in _documents([s])}
    result["false_alarms_on_clean_sets"] = sum(
        d.document_id in clean_ids for d in report.discrepancies
    )
    return {"mode": "truth", "seed": seed, "sets": n_sets, **result}


class _CacheOnly:
    """Stands in for the Anthropic client: this eval must never spend money."""

    @property
    def messages(self) -> "_CacheOnly":
        return self

    def parse(self, **_: Any) -> Any:
        raise LLMError("response not cached; run eval.runners.extraction_eval first")


def run_extracted(dataset: Path, model: str, variant: str) -> dict[str, Any]:
    manifest = json.loads((dataset / "manifest.json").read_text())
    llm = LLMClient(cache_dir=CACHE / "llm", anthropic_client=_CacheOnly())
    sets, documents, review = [], [], []
    incomplete: list[IncompleteDocument] = []
    for entry in manifest["sets"]:
        set_dir = dataset / entry["set_id"]
        doc_set = DocumentSet.model_validate_json((set_dir / "ground_truth.json").read_bytes())
        sets.append(doc_set)
        files = entry["files"] if variant == "digital" else entry["scans"]
        for truth in _documents([doc_set]):
            parsed = load_parsed(set_dir / files[truth.document_id])
            record = extract_document(parsed, llm, model, truth.document_id)
            if record.document is None:
                review.append(
                    {"document_id": truth.document_id, "errors": list(record.conversion_errors)}
                )
                raw = record.raw
                own_number = raw.doc_type == "purchase_order"
                incomplete.append(
                    IncompleteDocument(
                        document_id=truth.document_id,
                        doc_type=raw.doc_type,
                        po_number=raw.document_number if own_number else raw.po_reference,
                    )
                )
            else:
                documents.append(record.document)

    report = validate(documents, incomplete)
    result = score(_truth(sets), [(d.document_id, d.type.value) for d in report.discrepancies])
    in_review = {r["document_id"] for r in review}
    result["missed_but_in_review"] = [m for m in result["missed"] if m[0] in in_review]
    return {
        "mode": "extracted",
        "held": report.held,
        "dataset": str(dataset),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "variant": variant,
        "sent_to_review": review,
        **result,
    }


def _print(result: dict[str, Any]) -> None:
    label = result["mode"] + (f" / {result['variant']}" if "variant" in result else "")
    print(
        f"\n{label}: precision {result['precision']:.1%}, recall {result['recall']:.1%} "
        f"({result['true_positives']}/{result['injected']} found, "
        f"{len(result['false_positives'])} false alarms, {len(result['missed'])} missed)"
    )
    if "false_alarms_on_clean_sets" in result:
        print(f"false alarms on clean sets: {result['false_alarms_on_clean_sets']}")
    if result.get("sent_to_review"):
        print(f"sent to review (extraction incomplete): {len(result['sent_to_review'])}")
        for item in result["held"]:
            print(f"  held: {item}")
        for document_id, kind in result["missed_but_in_review"]:
            print(f"  missed, but its document is with a reviewer: {document_id} {kind}")
    print("| type | injected | found | false alarms | recall | precision |")
    print("|---|---|---|---|---|---|")
    for kind, row in result["per_type"].items():
        print(
            f"| {kind} | {row['injected']} | {row['found']} | {row['false_alarms']} "
            f"| {row['recall']:.0%} | {row['precision']:.0%} |"
        )
    for label, items in (("false alarm", result["false_positives"]), ("missed", result["missed"])):
        for document_id, kind in items:
            print(f"  {label}: {document_id} {kind}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.runners.discrepancy_eval")
    sub = parser.add_subparsers(dest="mode", required=True)
    t = sub.add_parser("truth")
    t.add_argument("--seed", type=int, default=7)
    t.add_argument("--sets", type=int, default=100)
    x = sub.add_parser("extracted")
    x.add_argument("--dataset", type=Path, required=True)
    x.add_argument("--model", default="claude-haiku-5-5")
    x.add_argument(
        "--variants", nargs="+", default=["digital", "scan"], choices=["digital", "scan"]
    )
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args(argv)

    if args.mode == "truth":
        results = [run_truth(args.seed, args.sets)]
        name = f"discrepancy-truth-seed{args.seed}-{args.sets}sets.json"
    else:
        results = [run_extracted(args.dataset, args.model, v) for v in args.variants]
        name = f"discrepancy-extracted-{args.dataset.name}-{args.model}.json"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / name).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    for result in results:
        _print(result)
    print(f"\nwrote {args.out / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
