"""Extraction evaluation: does the LLM read every field correctly?

For each document (digital and scan) and each model, the extraction is compared field by
field with the ground truth. Values are compared after parsing ("£1,234.56" == 1234.56), so
formatting differences do not count as errors but wrong digits do. Line items are matched
by SKU. The ground truth is the document *as written*, injected errors included: a correct
reader copies a wrong total, it does not fix it.

    uv run --env-file .env python -m eval.runners.extraction_eval \\
        --dataset data_generator/output/seed-42 --models claude-haiku-5-5 --max-cost 0.50

Every LLM response is cached by (file, prompt version, model), so re-running is free.
`--max-cost` stops the run before new spending would pass the limit; `--estimate` only
prints what a run would cost.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from backend.app.domain.document_set import DocumentSet
from backend.app.domain.documents import DeliveryNote, DNLine, Invoice, InvoiceLine, PurchaseOrder
from backend.app.extraction.extract import PROMPT_VERSION, extract_document, llm_input
from backend.app.extraction.normalise import parse_amount, parse_date, parse_quantity, parse_rate
from backend.app.extraction.schema import ExtractedDocument, ExtractedLine
from backend.app.ingestion.models import ParsedDocument
from backend.app.ingestion.parse import PARSE_VERSION, parse_pdf
from backend.app.llm.client import PRICES, CacheKey, LLMClient, cost_usd

Document = PurchaseOrder | DeliveryNote | Invoice
CACHE = Path(".cache")
# Typical tokens per document, measured in the pilot run (input ~3.2K, output up to ~1.2K).
ESTIMATE_TOKENS = {"input_tokens": 3_500, "output_tokens": 1_500}


@dataclass
class FieldCheck:
    path: str
    expected: str
    got: str
    correct: bool


# --- scoring -------------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(text.split())


def _same(parser: Callable[[str], Any] | None, expected: Any, got: str) -> bool:
    if parser is None:
        return _norm(str(expected)) == _norm(got)
    try:
        return bool(parser(got) == expected)
    except ValueError:
        return False


def score_extraction(truth: Document, raw: ExtractedDocument) -> tuple[list[FieldCheck], int]:
    """(one check per ground-truth field, number of extra lines the LLM invented)."""
    checks: list[FieldCheck] = []

    def check(
        path: str, expected: Any, got: str, parser: Callable[[str], Any] | None = None
    ) -> None:
        checks.append(FieldCheck(path, str(expected), got, _same(parser, expected, got)))

    checks.append(
        FieldCheck("doc_type", truth.doc_type, raw.doc_type, truth.doc_type == raw.doc_type)
    )
    for role in ("supplier", "buyer"):
        party, got_party = getattr(truth, role), getattr(raw, role)
        check(f"{role}.name", party.name, got_party.name)
        check(f"{role}.vat_number", party.vat_number, got_party.vat_number)

    if isinstance(truth, PurchaseOrder):
        check("document_number", truth.po_number, raw.document_number)
        check("issue_date", truth.issue_date, raw.issue_date, parse_date)
        check("net_total", truth.net_total, raw.net_total, parse_amount)
    elif isinstance(truth, DeliveryNote):
        check("document_number", truth.dn_number, raw.document_number)
        check("po_reference", truth.po_number, raw.po_reference)
        check("issue_date", truth.delivery_date, raw.issue_date, parse_date)
    else:
        check("document_number", truth.invoice_number, raw.document_number)
        check("po_reference", truth.po_number, raw.po_reference)
        checks.append(
            FieldCheck(
                "delivery_note_references",
                ", ".join(truth.delivery_note_numbers),
                ", ".join(raw.delivery_note_references),
                [_norm(r) for r in raw.delivery_note_references]
                == list(truth.delivery_note_numbers),
            )
        )
        check("issue_date", truth.issue_date, raw.issue_date, parse_date)
        check("due_date", truth.due_date, raw.due_date, parse_date)
        check("net_total", truth.net_total, raw.net_total, parse_amount)
        check("vat_total", truth.vat_total, raw.vat_total, parse_amount)
        check("gross_total", truth.gross_total, raw.gross_total, parse_amount)

    got_lines = {_norm(line.sku): line for line in raw.lines if line.sku}
    for line in truth.lines:
        p = f"lines[{line.sku}]"
        got = got_lines.get(line.sku, ExtractedLine())
        checks.append(FieldCheck(f"{p}.sku", line.sku, got.sku, line.sku in got_lines))
        if isinstance(line, DNLine):
            check(f"{p}.quantity", line.quantity_delivered, got.quantity, parse_quantity)
            continue
        check(f"{p}.quantity", line.quantity, got.quantity, parse_quantity)
        check(f"{p}.unit_price", line.unit_price, got.unit_price, parse_amount)
        check(f"{p}.vat_rate", line.vat_rate, got.vat_rate, parse_rate)
        check(f"{p}.line_net", line.line_net, got.line_net, parse_amount)
        if isinstance(line, InvoiceLine):
            check(f"{p}.line_vat", line.line_vat, got.line_vat, parse_amount)
    extra = len(got_lines.keys() - {line.sku for line in truth.lines})
    return checks, extra


# --- running -------------------------------------------------------------------------


@dataclass
class DocResult:
    set_id: str
    document_id: str
    template: str
    variant: str
    model: str
    fields: int
    correct: int
    doc_type_correct: bool
    header_correct: int
    header_fields: int
    line_correct: int
    line_fields: int
    extra_lines: int
    unverified: int
    located: int
    conversion_errors: int
    cost_usd: str
    cached: bool
    seconds: float
    wrong: list[dict[str, str]]


def _documents(doc_set: DocumentSet) -> list[Document]:
    return [doc_set.purchase_order, doc_set.delivery_note, *doc_set.invoices]


def _jobs(
    dataset: Path, variants: Sequence[str]
) -> list[tuple[DocumentSet, str, Document, str, Path]]:
    manifest = json.loads((dataset / "manifest.json").read_text())
    jobs = []
    for entry in manifest["sets"]:
        set_dir = dataset / entry["set_id"]
        doc_set = DocumentSet.model_validate_json((set_dir / "ground_truth.json").read_bytes())
        for document in _documents(doc_set):
            for variant in variants:
                files = entry["files"] if variant == "digital" else entry["scans"]
                jobs.append(
                    (
                        doc_set,
                        entry["template"],
                        document,
                        variant,
                        set_dir / files[document.document_id],
                    )
                )
    return jobs


def _is_cached(path: Path, model: str) -> bool:
    parsed = load_parsed(path)
    key = CacheKey(
        file_sha256=parsed.sha256,
        input_sha256=hashlib.sha256(llm_input(parsed).encode()).hexdigest(),
        prompt_version=PROMPT_VERSION,
        model=model,
    )
    return (CACHE / "llm" / f"{key.digest()}.json").exists()


def estimate_per_doc(model: str) -> Decimal:
    return cost_usd(model, **ESTIMATE_TOKENS)


def load_parsed(path: Path) -> ParsedDocument:
    """Parse once per file content; Docling takes seconds per page, the cache milliseconds."""
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    cached = CACHE / "parsed" / f"{sha}-parse-v{PARSE_VERSION}.json"
    if cached.exists():
        return ParsedDocument.model_validate_json(cached.read_bytes())
    parsed = parse_pdf(path)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(parsed.model_dump_json(), encoding="utf-8")
    return parsed


def run(
    dataset: Path, models: Sequence[str], variants: Sequence[str], max_cost: Decimal
) -> tuple[list[DocResult], Decimal, bool]:
    """(results, money spent in this run, stopped early by the cost limit)."""
    llm = LLMClient(cache_dir=CACHE / "llm")
    results: list[DocResult] = []
    spent = Decimal(0)
    for doc_set, template, truth, variant, path in _jobs(dataset, variants):
        for model in models:
            if not _is_cached(path, model) and spent + estimate_per_doc(model) > max_cost:
                print(
                    f"\nstopping: next call could pass --max-cost ${max_cost} (spent ${spent:.4f})"
                )
                return results, spent, True
            record = extract_document(load_parsed(path), llm, model, truth.document_id)
            if not record.cached:
                spent += record.usage.cost_usd
            checks, extra = score_extraction(truth, record.raw)
            header = [c for c in checks if not c.path.startswith("lines[") and c.path != "doc_type"]
            lines = [c for c in checks if c.path.startswith("lines[")]
            located = [p for p in record.provenance.values()]
            results.append(
                DocResult(
                    set_id=doc_set.set_id,
                    document_id=truth.document_id,
                    template=template,
                    variant=variant,
                    model=model,
                    fields=len(checks),
                    correct=sum(c.correct for c in checks),
                    doc_type_correct=checks[0].correct,
                    header_correct=sum(c.correct for c in header),
                    header_fields=len(header),
                    line_correct=sum(c.correct for c in lines),
                    line_fields=len(lines),
                    extra_lines=extra,
                    unverified=sum(p is None for p in located),
                    located=len(located),
                    conversion_errors=len(record.conversion_errors),
                    cost_usd=str(record.usage.cost_usd),
                    cached=record.cached,
                    seconds=record.seconds,
                    wrong=[asdict(c) for c in checks if not c.correct],
                )
            )
            mark = (
                "ok"
                if results[-1].correct == results[-1].fields
                else f"{len(results[-1].wrong)} wrong"
            )
            print(f"  {truth.document_id:<16} {variant:<7} {model:<18} {mark}", flush=True)
    return results, spent, False


def summarise(results: Sequence[DocResult]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[DocResult]] = {}
    for r in results:
        groups.setdefault((r.model, r.variant), []).append(r)
    rows = []
    for (model, variant), rs in sorted(groups.items()):
        n = len(rs)
        rows.append(
            {
                "model": model,
                "variant": variant,
                "documents": n,
                "doc_type_accuracy": round(sum(r.doc_type_correct for r in rs) / n, 4),
                "header_accuracy": round(
                    sum(r.header_correct for r in rs) / sum(r.header_fields for r in rs), 4
                ),
                "line_accuracy": round(
                    sum(r.line_correct for r in rs) / max(1, sum(r.line_fields for r in rs)), 4
                ),
                "documents_fully_correct": round(
                    sum(r.correct == r.fields and r.extra_lines == 0 for r in rs) / n, 4
                ),
                "unverified_rate": round(
                    sum(r.unverified for r in rs) / max(1, sum(r.located for r in rs)), 4
                ),
                "cost_per_doc_usd": str(
                    (sum((Decimal(r.cost_usd) for r in rs), Decimal(0)) / n).quantize(
                        Decimal("0.0001")
                    )
                ),
                "median_seconds": sorted(r.seconds for r in rs)[n // 2],
            }
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.runners.extraction_eval")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=["claude-opus-5-5"], choices=sorted(PRICES))
    parser.add_argument(
        "--variants", nargs="+", default=["digital", "scan"], choices=["digital", "scan"]
    )
    parser.add_argument(
        "--max-cost", type=Decimal, default=Decimal("1.00"), help="USD, new spending only"
    )
    parser.add_argument("--estimate", action="store_true", help="print the expected cost and exit")
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args(argv)

    jobs = _jobs(args.dataset, args.variants)
    print("Expected new spending (cached responses are free):")
    total = Decimal(0)
    for model in args.models:
        todo = sum(not _is_cached(path, model) for *_, path in jobs)
        cost = todo * estimate_per_doc(model)
        total += cost
        print(f"  {model:<18} {todo:>3} of {len(jobs)} documents uncached  ~${cost:.2f}")
    print(f"  total ~${total:.2f}   (limit --max-cost ${args.max_cost})")
    if args.estimate:
        return 0

    results, spent, stopped = run(args.dataset, args.models, args.variants, args.max_cost)
    summary = summarise(results)
    report = {
        "prompt_version": PROMPT_VERSION,
        "dataset": str(args.dataset),
        "spent_this_run_usd": str(spent),
        "complete": not stopped,
        "summary": summary,
        "documents": [asdict(r) for r in results],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"extraction-{args.dataset.name}-{PROMPT_VERSION}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nspent this run: ${spent:.4f}; wrote {out}")
    print(
        "| model | variant | docs | type | header | lines | docs fully correct "
        "| unverified | $/doc | median s |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in summary:
        print(
            f"| {r['model']} | {r['variant']} | {r['documents']} | {r['doc_type_accuracy']:.0%} "
            f"| {r['header_accuracy']:.1%} | {r['line_accuracy']:.1%} "
            f"| {r['documents_fully_correct']:.0%} "
            f"| {r['unverified_rate']:.1%} | {r['cost_per_doc_usd']} | {r['median_seconds']} |"
        )
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
