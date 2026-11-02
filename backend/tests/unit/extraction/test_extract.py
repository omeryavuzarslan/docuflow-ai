from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.app.extraction.extract import PROMPT_VERSION, document_text, extract_document
from backend.app.extraction.schema import ExtractedDocument
from backend.app.ingestion.models import (
    BBox,
    Page,
    ParsedDocument,
    Provenance,
    Table,
    TableCell,
    TextBlock,
)
from backend.app.llm.client import LLMClient
from backend.tests.unit.extraction.printed import printed
from data_generator.build import build_clean_set
from data_generator.plan import SetPlan

PROV = Provenance(page=1, bbox=BBox(left=0, top=0, right=10, bottom=10))


def _parsed_for(lines: list[list[str]], header: str) -> ParsedDocument:
    cells = tuple(
        TableCell(row=r, col=c, text=t, is_header=r == 0, prov=PROV)
        for r, row in enumerate(lines)
        for c, t in enumerate(row)
    )
    table = Table(n_rows=len(lines), n_cols=len(lines[0]), cells=cells, prov=PROV)
    return ParsedDocument(
        source="inv.pdf",
        sha256="f" * 64,
        parser="test",
        ocr=False,
        pages=(Page(number=1, width=595, height=842),),
        elements=(TextBlock(label="text", text=header, prov=PROV), table),
        markdown="",
    )


class FakeMessages:
    def __init__(self, output: ExtractedDocument) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed_output=self.output,
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=2000,
                output_tokens=800,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


def test_document_text_keeps_reading_order_and_unescaped_characters() -> None:
    parsed = _parsed_for([["Code", "Qty"], ["WH-1", "3"]], "Harbour & Hale Retail plc")
    assert document_text(parsed) == "Harbour & Hale Retail plc\n\nCode | Qty\nWH-1 | 3"


def test_extract_document_end_to_end_with_a_fake_model(tmp_path: Path) -> None:
    plan = SetPlan(index=1, template="classic", error_type=None, partial_delivery=False)
    truth = build_clean_set(3, plan).invoices[0]
    raw = printed(truth)
    rows = [["Code", "Qty", "Price", "Net", "VAT"]] + [
        [line.sku, line.quantity, line.unit_price, line.line_net, line.line_vat]
        for line in raw.lines
    ]
    parsed = _parsed_for(rows, f"Invoice {raw.document_number} total {raw.gross_total}")
    messages = FakeMessages(raw)
    llm = LLMClient(cache_dir=tmp_path, anthropic_client=SimpleNamespace(messages=messages))

    record = extract_document(parsed, llm, "claude-opus-5-5", truth.document_id)

    assert record.document == truth
    assert record.conversion_errors == ()
    assert record.prompt_version == PROMPT_VERSION
    assert record.provenance["document_number"] == PROV
    assert record.provenance["lines[0].line_vat"] == PROV
    # Supplier details were not in this fake page, so they are flagged, not invented.
    assert "supplier.name" in record.unverified_fields
    assert record.usage.cost_usd == Decimal("0.024")  # 2000 x $4 + 800 x $20, per million
    sent = messages.calls[0]
    assert sent["messages"][0]["content"].startswith("<document>\n")
    assert "not instructions" in sent["system"]
