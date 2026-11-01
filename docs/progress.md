# Progress log

Updated at the end of each session.

## 2026-11-01
- Reviewed and revised CLAUDE.md: Claude writes the code, rounding rule (ROUND_HALF_UP,
  VAT per line), error injection rules, injected-error record shape, determinism scope,
  NUMERIC precision, Commands section. Progress log moved here.
- Next: Week 1 — domain models + data generator v1.
- Project skeleton (branch `chore/project-setup`): git + GitHub remote, uv project on
  Python 3.12, ruff/mypy (strict, pydantic plugin)/pytest config, package skeleton,
  .gitignore, README, MIT licence. CLAUDE.md moved to repo root so it loads every session.
- Decision: document type (invoice/PO/DN) is classified by the extraction LLM call, with
  classification accuracy measured (roadmap step 3).
- Domain models (branch `feat/domain-models`): Decimal-only numeric types fixed to DB scale
  (floats rejected, also from JSON), frozen + extra="forbid" models, separate PO/DN/invoice
  line types, stored (not computed) totals, InjectedError with shape validation,
  DocumentSet with reference checks, calculations.py (ROUND_HALF_UP, per-line VAT).
  ADR-0001 records the rounding decision and the multi-method VAT rule for step 4.
  37 tests passing; ruff and mypy strict clean.
- Next: data generator v1 (design to be approved first).
- Data generator v1, ground-truth JSON (branch `feat/data-generator`): 8 sets (2 clean +
  one set per error type; changed from 5 sets so errors never interact), per-set seeded
  RNG streams (adding sets never changes earlier ones), hand-written catalogue with
  sub-penny prices and fractional quantities, partial delivery as a false-positive trap,
  validated `evolve` instead of `model_copy`, arithmetic errors >= 50p so they cannot be
  confused with a legitimate rounding method. Output byte-identical across processes.
  1053 tests passing (property-style checks over 30-50 seeds).
- Next: PDF rendering (Jinja2 + WeasyPrint, 2 templates); design to be approved first.
- PDF rendering (branch `feat/pdf-rendering`): Jinja2 + WeasyPrint, `classic` and `modern`
  templates with different labels, column order and layout. PDFs show documents exactly as
  stored (injected errors included). Output, including PDFs, is byte-identical across runs;
  manifest maps document_id -> PDF file. macOS: uv's Python needs Homebrew's lib dir on the
  dyld fallback path, set in `render._import_weasyprint`. Modern header uses tables because
  WeasyPrint's flex/grid overflowed the page (found by viewing the PDFs; text tests missed it).
- Week 1 done. Next: roadmap step 2, Docling parsing (+ simulated scans with OCR).
- Docling parsing (branch `feat/docling-parsing`): `backend/app/ingestion` wraps Docling
  behind our own ParsedDocument model (text blocks + tables with cells, top-left page
  coordinates, sha256, parser version). Auto OCR when a PDF has no text layer (RapidOCR via
  Docling "auto"; EasyOCR is not bundled in docling 2.145). Simulated scans per document
  (`*.scan.pdf`, seeded, byte-identical). Parse eval: digital 100% value recall, scans 98.8%
  (OCR letter/digit and punctuation errors); see docs/experiments.md. Slow Docling tests are
  marked `slow` and skipped by default. Disk ran nearly full during model download; cleared
  the uv cache (~2.6 GB).
- Step 3 decision: LLM provider is Claude (Anthropic API). Main model `claude-opus-5-5`;
  `claude-sonnet-5-5` and `claude-haiku-5-5` proposed as cost comparisons (not yet confirmed).
- Step 3 design (proposed, awaiting OK; no code yet):
  - one `messages.parse()` call per document returns doc type + fields; amounts copied as
    printed strings, Python converts to Decimal and builds the domain model (LLM does no math);
  - provenance: Python locates each extracted value in the ParsedDocument (page + bbox);
    not found => field flagged unverified (also a hallucination check);
  - LLM wrapper in backend/app/llm with a disk cache keyed by (file sha256, prompt version,
    model); versioned prompts; document text treated as data (prompt-injection rule);
  - eval: doc-type accuracy, header field accuracy, line field accuracy, per digital/scan and
    per model, with cost and latency;
  - unit tests without API calls; one live test marked `slow`, skipped without a key.
- Blocker for live runs: no ANTHROPIC_API_KEY on this machine. User to create a key and put
  `ANTHROPIC_API_KEY=...` in `.env` (gitignored).
- Next: user confirms design + comparison models, then implement on `feat/llm-extraction`.
