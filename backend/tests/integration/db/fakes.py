"""Fakes for pipeline and API tests: no Docling, no API calls, no cost.

A fake "PDF" is `%PDF-fake` followed by a generated document id. The fake parser turns it
into a one-block ParsedDocument holding that id; the fake LLM answers with the perfect
extraction of that document, unless the id is in `broken`.
"""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.app.domain.document_set import DocumentSet
from backend.app.extraction.schema import ExtractedDocument, ExtractedParty
from backend.app.ingestion.models import BBox, Page, ParsedDocument, Provenance, TextBlock
from backend.app.llm.client import LLMClient
from backend.app.pipeline.process import Services
from backend.app.validation.rules import Document
from backend.tests.unit.extraction.printed import printed

FAKE_PDF_PREFIX = b"%PDF-fake\n"


def fake_pdf(truth_id: str) -> bytes:
    return FAKE_PDF_PREFIX + truth_id.encode()


OWNER = "owner-a"
PROV = Provenance(page=1, bbox=BBox(left=0, top=0, right=1, bottom=1))


class FakeWorld:
    def __init__(self, sets: list[DocumentSet], tmp_path: Path) -> None:
        self.truth: dict[str, Document] = {}
        for s in sets:
            documents: list[Document] = [s.purchase_order, s.delivery_note, *s.invoices]
            for d in documents:
                self.truth[d.document_id] = d
        self.broken: set[str] = set()
        self.calls = 0
        fake_anthropic = SimpleNamespace(messages=SimpleNamespace(parse=self.parse_llm))
        self.services = Services(
            parse=self.parse_pdf,
            llm=LLMClient(cache_dir=tmp_path / "llm", anthropic_client=fake_anthropic),
            model="claude-haiku-5-5",
            storage_root=tmp_path / "storage",
        )

    @property
    def root(self) -> Path:
        return self.services.storage_root

    def parse_pdf(self, path: Path) -> ParsedDocument:
        data = path.read_bytes()
        return ParsedDocument(
            source=path.name,
            sha256=hashlib.sha256(data).hexdigest(),
            parser="fake",
            ocr=False,
            pages=(Page(number=1, width=595, height=842),),
            elements=(
                TextBlock(
                    label="text", text=data.removeprefix(FAKE_PDF_PREFIX).decode(), prov=PROV
                ),
            ),
            markdown="",
        )

    # Stands in for anthropic.Anthropic().messages
    def parse_llm(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        truth_id = kwargs["messages"][0]["content"].split("\n")[1]
        output: ExtractedDocument = printed(self.truth[truth_id])
        if truth_id in self.broken:
            output = output.model_copy(update={"supplier": ExtractedParty()})
        return SimpleNamespace(
            parsed_output=output,
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=300,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
