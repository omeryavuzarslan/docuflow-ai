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
- Step 3, LLM extraction (branch `feat/llm-extraction`):
  - `backend/app/extraction`: ExtractedDocument schema (all strings, as printed; empty
    string = absent; every field required in the JSON schema, because the API rejected the
    first schema as "too complex"), strict parsers to Decimal/date (no OCR "repairs"),
    to_domain with per-field error list, provenance lookup in the ParsedDocument.
  - `backend/app/llm`: LLMClient (`messages.parse`, effort low, disk cache keyed by file
    hash + input-text hash + prompt version + model, USD cost as Decimal); versioned prompts
    `extract-v1`, `extract-v2`.
  - Parser fix (parse-v2): keep Docling's furniture layer; the modern template's header band
    (issuer address + VAT number) was being dropped.
  - Eval `eval/runners/extraction_eval.py` with `--estimate` and `--max-cost`.
  - Results (docs/experiments.md): v1 all three models, $1.95; v2 Haiku: digital 100% of
    documents fully correct, scans 80%, $0.0007/doc. Default extractor: Haiku 5.5.
  - API spend so far ~$2.04 of $5 credit.
- Step 4, matching + rules (branch `feat/matching-rules`): `backend/app/matching` (PO +
  supplier VAT grouping, SKU keys ignoring punctuation), `backend/app/validation` (R1-R8, M1,
  Discrepancy model, held checks for documents under review), ADR-0002 (tolerances per HMRC
  VAT Notice 700 17.5, known limits), `eval/runners/discrepancy_eval.py` (truth and
  end-to-end modes, cache-only, $0). Results: rules alone 100%/100% on 100 sets; end to end
  digital 100%/100%; scans 100% precision, 5/6 recall (miss is in a reviewed document).
- Step 4 merged (PR #7).
- Step 5a, database (branch `feat/database`): docker-compose with pgvector/pgvector:0.8.0-pg17
  on port 5433 (+ `docuflow_test` database), SQLAlchemy 2 models for 12 tables, hand-written
  domain <-> row mapping, Alembic with the initial migration, DB integration tests (schema
  matches migrations, round trip of every document type, owner-scoped uniqueness, raw vs
  corrected kept apart), `.env.example`, ADR-0003. DB tests skip when the database is down.
- Step 5a merged (PR #8).
- Step 5b, worker (branch `feat/worker`): Postgres job queue (claim with FOR UPDATE SKIP
  LOCKED, retries with 10/20/40 s backoff, stale-lock requeue), pipeline (ingest_file ->
  process_document: parse, extract, versioned extraction rows, typed rows, revalidate owner;
  needs_review + held checks; dismissed/resolved findings kept), worker CLI with
  --until-empty / --cache-only, load_dataset CLI. Two migrations: `documents.received_seq`
  (arrival order decides which identical invoice is the duplicate; UUID ordering made tests
  flaky) and `extractions.cached` (spend reports must not count cache hits).
  Real run: seed-42's 25 PDFs through Docling + cached Haiku -> all done, exactly the 6
  injected errors in `discrepancies`, $0 spent.
- Step 5b merged (PR #9).
- Step 5c, API (branch `feat/api`): FastAPI app (`backend/app/api`) with health, upload
  (PDF magic-byte check, 20 MB limit, dedupe -> 200), document list/detail (typed document,
  latest raw extraction, provenance, corrections, findings), original file download,
  corrections (field paths, raw kept, document rebuilt, revalidated; moves needs_review
  documents to done), findings list/filter and status update, job status. Owner via
  `X-Owner-Id`; other owners get 404. Migration: `corrections.seq` (ordering). Shared test
  fakes in `backend/tests/integration/db/fakes.py`. Tried live: /docs page and
  GET /discrepancies on the demo data return the 6 findings.
- Next: commit + PR for 5c; then roadmap step 6 (RAG v1: eval set first).
