"""Parse evaluation: how much of the ground truth survives PDF parsing?

For every document (digital and scanned) we list the values a reader would need, formatted
exactly as the PDF prints them, and check whether the parser's output contains them:

- header values (document number, dates, totals) anywhere in the parsed text;
- line values (quantity, price, amounts) in the *same table row* as the line's SKU, so
  that a quantity found somewhere else on the page does not count.

This measures parsing only. Whether an LLM then extracts the right fields is step 3.

    uv run python -m eval.runners.parse_eval --dataset data_generator/output/seed-42
"""

import argparse
import json
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.app.domain.document_set import DocumentSet
from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder
from backend.app.ingestion.models import ParsedDocument
from backend.app.ingestion.parse import PARSER, parse_pdf
from data_generator.render import format_date, format_money, format_price, format_quantity

Document = PurchaseOrder | DeliveryNote | Invoice


@dataclass
class DocResult:
    set_id: str
    document_id: str
    template: str
    variant: str  # "digital" or "scan"
    found: int
    total: int
    line_table_found: bool
    seconds: float
    missed: list[str] = field(default_factory=list)


def expected_values(document: Document) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """(header values, [(sku, line values), ...]) as printed on the PDF."""
    if isinstance(document, PurchaseOrder):
        header = [
            document.po_number,
            format_date(document.issue_date),
            format_money(document.net_total),
        ]
        lines = [
            (
                line.sku,
                [
                    format_quantity(line.quantity),
                    format_price(line.unit_price),
                    format_money(line.line_net),
                ],
            )
            for line in document.lines
        ]
    elif isinstance(document, DeliveryNote):
        header = [document.dn_number, document.po_number, format_date(document.delivery_date)]
        lines = [(line.sku, [format_quantity(line.quantity_delivered)]) for line in document.lines]
    else:
        header = [
            document.invoice_number,
            document.po_number,
            format_date(document.issue_date),
            format_date(document.due_date),
            format_money(document.net_total),
            format_money(document.vat_total),
            format_money(document.gross_total),
        ]
        lines = [
            (
                line.sku,
                [
                    format_quantity(line.quantity),
                    format_price(line.unit_price),
                    format_money(line.line_net),
                    format_money(line.line_vat),
                ],
            )
            for line in document.lines
        ]
    return header, lines


def score(document: Document, parsed: ParsedDocument) -> tuple[int, int, list[str], bool]:
    """(found, total, missed values, line table found)."""
    header, lines = expected_values(document)
    text = _normalise(parsed.full_text())
    rows = [_normalise(" | ".join(row)) for table in parsed.tables() for row in table.rows()]

    missed = [value for value in header if _normalise(value) not in text]
    for sku, values in lines:
        row = next((r for r in rows if sku in r), None)
        missed += [
            f"{sku}:{value}"
            for value in [sku, *values]
            if row is None or _normalise(value) not in row
        ]
    total = len(header) + sum(1 + len(values) for _, values in lines)
    line_table = any(table.n_rows == len(lines) + 1 for table in parsed.tables())
    return total - len(missed), total, missed, line_table


def run(dataset: Path) -> list[DocResult]:
    manifest = json.loads((dataset / "manifest.json").read_text())
    results = []
    for entry in manifest["sets"]:
        set_dir = dataset / entry["set_id"]
        doc_set = DocumentSet.model_validate_json((set_dir / "ground_truth.json").read_bytes())
        documents: list[Document] = [
            doc_set.purchase_order,
            doc_set.delivery_note,
            *doc_set.invoices,
        ]
        for document in documents:
            for variant, files in (("digital", entry["files"]), ("scan", entry["scans"])):
                path = set_dir / files[document.document_id]
                start = time.perf_counter()
                parsed = parse_pdf(path)
                seconds = time.perf_counter() - start
                found, total, missed, line_table = score(document, parsed)
                results.append(
                    DocResult(
                        set_id=doc_set.set_id,
                        document_id=document.document_id,
                        template=doc_set.template,
                        variant=variant,
                        found=found,
                        total=total,
                        line_table_found=line_table,
                        seconds=round(seconds, 2),
                        missed=missed,
                    )
                )
                print(f"  {document.document_id:<16} {variant:<7} {found}/{total}", flush=True)
    return results


def summarise(results: Sequence[DocResult]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[DocResult]] = {}
    for r in results:
        groups.setdefault((r.variant, r.template), []).append(r)
        groups.setdefault((r.variant, "all"), []).append(r)
    summary = []
    for (variant, template), rs in sorted(groups.items()):
        found, total = sum(r.found for r in rs), sum(r.total for r in rs)
        summary.append(
            {
                "variant": variant,
                "template": template,
                "documents": len(rs),
                "value_recall": round(found / total, 4),
                "line_table_found": round(sum(r.line_table_found for r in rs) / len(rs), 4),
                "median_seconds": sorted(r.seconds for r in rs)[len(rs) // 2],
            }
        )
    return summary


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.runners.parse_eval")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args(argv)

    # Load the models once before timing anything, so the first document is not penalised.
    first = next(args.dataset.glob("set-*/po.pdf"))
    warm_start = time.perf_counter()
    parse_pdf(first)
    parse_pdf(first, ocr=True)
    warm_up = round(time.perf_counter() - warm_start, 1)

    results = run(args.dataset)
    summary = summarise(results)
    report = {
        "parser": PARSER,
        "dataset": str(args.dataset),
        "warm_up_seconds": warm_up,
        "summary": summary,
        "documents": [asdict(r) for r in results],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"parse-{args.dataset.name}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nwarm-up {warm_up}s; wrote {out}")
    print("| variant | template | docs | value recall | line table found | median s/doc |")
    print("|---|---|---|---|---|---|")
    for row in summary:
        print(
            f"| {row['variant']} | {row['template']} | {row['documents']} "
            f"| {row['value_recall']:.1%} | {row['line_table_found']:.0%} "
            f"| {row['median_seconds']} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
