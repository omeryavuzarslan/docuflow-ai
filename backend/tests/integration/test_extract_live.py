"""One real Claude call (Haiku, ~$0.001): `uv run --env-file .env pytest -m live`.

Checks what the unit tests' fake client cannot: that the API accepts our schema and that
the model returns a parseable extraction. Skipped without an API key.
"""

import os
import re
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.domain.documents import Invoice
from backend.app.extraction.extract import extract_document
from backend.app.ingestion.models import BBox, Page, ParsedDocument, Provenance, TextBlock
from backend.app.llm.client import LLMClient
from data_generator.build import build_clean_set
from data_generator.plan import SetPlan
from data_generator.render import render_html

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="no ANTHROPIC_API_KEY"),
]


def test_haiku_extracts_a_digital_invoice(tmp_path: Path) -> None:
    plan = SetPlan(index=1, template="classic", error_type=None, partial_delivery=False)
    truth = build_clean_set(42, plan).invoices[0]
    # Plain text of the rendered page, so the test does not need Docling.
    text = re.sub(r"<[^>]+>", " ", render_html(truth, "classic").split("<body>")[1])
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    prov = Provenance(page=1, bbox=BBox(left=0, top=0, right=595, bottom=842))
    parsed = ParsedDocument(
        source="live.pdf",
        sha256="live-test",
        parser="test",
        ocr=False,
        pages=(Page(number=1, width=595, height=842),),
        elements=(TextBlock(label="text", text=text, prov=prov),),
        markdown="",
    )

    record = extract_document(parsed, LLMClient(cache_dir=tmp_path), "claude-haiku-5-5", "doc")

    assert record.cached is False
    assert record.raw.doc_type == "invoice"
    assert isinstance(record.document, Invoice), record.conversion_errors
    assert record.document.gross_total == truth.gross_total
    assert record.usage.cost_usd < Decimal("0.01")
