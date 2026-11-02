# DocuFlow AI

Document intelligence + RAG portfolio project. Processes invoices, purchase orders (PO) and
delivery notes (DN): parses PDFs, extracts structured data, matches related documents
(three-way matching), flags discrepancies with deterministic rules, and answers questions
with grounded, cited answers. Evaluation is a first-class feature, not an afterthought.

## How to work with me (IMPORTANT)

I am a final-year AI student building this for my CV. I am new to most of this stack and
will learn it as we go. Claude writes the code; I direct, approve and must be able to
explain every design decision in an interview.

- Explain things in plain language. Introduce new concepts briefly when they first come up
  (what it is, why we need it), without assuming prior knowledge.
- Make sensible technical decisions yourself and record them (in this file or an ADR in
  `docs/adr/`). Only ask me when the choice affects scope, cost or what the project shows.
- Before writing a non-trivial module, explain the approach in a few sentences and wait
  for my OK.
- For core modules (`matching/`, `validation/`, `rag/` retrieval, `eval/` metrics):
  propose the design and tests first, then implement after my OK. After implementing,
  summarise the key decisions and non-obvious parts so I can explain them.
- Keep changes small and reviewable. One logical change per commit, conventional commit
  messages (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`).
- Never commit or push without my explicit approval.
- Git: one branch per task (`feat/...`, `fix/...`, `chore/...`, `docs/...`), merged into
  `main`. Remote: https://github.com/omeryavuzarslan/docuflow-ai (public).
- At the end of each session, update `docs/progress.md`.

## Commands

```
uv sync                              # install dependencies
docker compose up -d db              # Postgres 17 + pgvector on localhost:5433
uv run --env-file .env alembic upgrade head   # create/upgrade tables
uv run --env-file .env python -m backend.app.pipeline.load_dataset --dataset data_generator/output/seed-42 --owner demo
uv run --env-file .env python -m backend.app.worker --until-empty --cache-only   # process queue, no API spend
uv run --env-file .env uvicorn backend.app.api.main:app --reload   # API; docs at http://localhost:8000/docs
uv run pytest                        # tests (fast; skips `slow`; DB tests need the db up)
uv run pytest -m slow                # Docling model tests (~30 s)
uv run --env-file .env pytest -m live   # paid Claude API tests
uv run ruff check . && uv run ruff format .
uv run mypy backend data_generator eval
uv run python -m data_generator --seed 42 --sets 8
uv run python -m eval.runners.parse_eval --dataset data_generator/output/seed-42
uv run --env-file .env python -m eval.runners.extraction_eval --dataset data_generator/output/seed-42 --estimate
uv run python -m eval.runners.discrepancy_eval truth --seed 7 --sets 100
uv run python -m eval.runners.discrepancy_eval extracted --dataset data_generator/output/seed-42
uv run --env-file .env python -m eval.runners.retrieval_eval --dataset data_generator/output/seed-42
```

macOS needs `brew install pango` for WeasyPrint. Docling downloads ~500 MB of models to
`~/.cache/huggingface` on first use.

## Engineering rules

- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 + Alembic, PostgreSQL + pgvector.
- Package management: `uv`. Lint/format: `ruff`. Types: `mypy`. Tests: `pytest`.
- Money is ALWAYS `Decimal` in Python. Never float. In Postgres: amounts `NUMERIC(12,2)`,
  unit prices and quantities `NUMERIC(12,4)`.
- Rounding: always `quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`. Never rely on
  Python's default (banker's rounding). VAT is calculated per line, rounded per line, then
  summed (the per-line vs per-invoice choice is recorded in an ADR).
- Arithmetic, comparisons and matching are deterministic Python. The LLM never does math
  and never decides whether a discrepancy exists.
- Pydantic domain models in `backend/app/domain/` are the single source of truth for the
  data generator and extraction schemas. SQLAlchemy models are written separately with
  explicit mapping functions to/from the domain models; a test checks they stay in sync.
- LLM calls go through one client wrapper (`backend/app/llm/client.py`) with a disk cache
  keyed by `(file_hash, input_text_hash, prompt_version, model)`. Prompts are versioned
  files and never edited once results depend on them. Provider: Claude (Anthropic API);
  default extractor `claude-haiku-5-5` (see docs/experiments.md). Every paid run first
  prints an estimate and respects `--max-cost`.
- Store provenance (page + bbox) for every extracted field.
- Keep raw LLM extraction and human-corrected values separate and versioned.
- The LLM never writes SQL. Structured questions use fixed, parameterised query functions.
- Every retrieval query is scoped by `owner_id`.
- Every component must earn its place with a measured result in `docs/experiments.md`.

## NOT doing

Kubernetes, microservices, Celery/Redis, LangChain/LlamaIndex/LangGraph, fine-tuning,
text-to-SQL, real-time collaboration. A Postgres `jobs` table + worker
(`SELECT ... FOR UPDATE SKIP LOCKED`) is the job queue.

## Repository layout (target)

```
backend/app/{api,domain,ingestion,extraction,matching,validation,rag,llm,db}/
backend/app/worker.py
backend/migrations/          # Alembic
backend/tests/{unit,integration}/
frontend/                    # React + Vite
data_generator/              # synthetic documents: ground truth JSON first, then PDF
data_generator/tests/        # generator tests (backend tests live in backend/tests/)
eval/{datasets,runners,results}/
docs/{architecture.md,experiments.md,progress.md,adr/}
docker-compose.yml
.github/workflows/
```

## Roadmap

MVP (target mid-January 2027):
1. Domain models + synthetic data generator v1
2. Docling parsing (+ simulated scans with OCR)
3. LLM structured extraction + extraction eval. The same LLM call also classifies the
   document type (invoice / PO / DN); classification accuracy is measured against the
   synthetic ground truth. No manual type selection on upload.
4. Matching + rule engine + discrepancy precision/recall
   (quantity rule: invoiced qty > delivered qty on the DN; a DN below the PO qty is a
   partial delivery, not an error)
5. Postgres + FastAPI + background worker
6. RAG v1: eval set first, structure-aware chunking, dense retrieval, Recall@K / MRR
7. Hybrid search (Postgres FTS + RRF), query router, cited answers
8. React UI: upload, review/correct, discrepancies, chat with citations
9. Docker Compose + GitHub Actions (ruff, mypy, pytest, cached eval smoke test)
10. Deploy (Azure) + README with architecture diagram and results
11. Buffer

Advanced (target end of March 2027): 30 document sets with noisy scans and many-to-many
matching, retrieval experiments (chunking, embeddings, reranking), supplier contracts
doc type + contract-price rule, prompt-injection and tenant-isolation tests, tracing and
cost/latency metrics, validated LLM-as-judge, write-up and demo video.

## Current task: Week 1 — domain models + data generator v1

Goals:
- Pydantic models: Supplier, Address, LineItem, PurchaseOrder, DeliveryNote, Invoice,
  plus an injected-error record: `type`, `document_id`, `field: str | None`,
  `expected`, `actual`, `related_document_id: str | None` (for set-level errors such as
  duplicate invoice, where `field` is None).
- Generator that builds a consistent PO -> DN -> Invoice set as ground-truth JSON FIRST,
  then optionally injects labelled errors, then renders PDFs.
- Error injection rules (one injected error = exactly one recorded error):
  - quantity / unit price mismatch: change the invoice value and recompute its line
    total, VAT and totals, so the invoice is internally consistent and the only error
    is the mismatch against PO/DN.
  - line total / VAT / total error: change only that field, do not recompute anything.
  - duplicate invoice: copy an existing invoice with a new document id.
- Rendering: Jinja2 HTML templates -> PDF (WeasyPrint; if its system libraries are a
  problem on this OS, use Playwright `page.pdf()`).
- 2 visually different templates, 8 document sets, error types: quantity mismatch,
  unit price mismatch, line total error, VAT error, total error, duplicate invoice.
- At least 2 of the 8 sets are clean (no injected errors), to measure false positives.
  v1 has exactly one injected error per erroneous set (2 clean + 6 single-error sets), so
  errors cannot interact and every detection maps to one injected error. At least one
  clean set has a partial delivery (DN qty < PO qty), a deliberate false-positive trap.
  Multi-error sets come with the 30-set advanced dataset.
- Ground-truth JSON: Decimals serialised as strings, keys in a stable order.
- UK conventions: GBP, 20% standard VAT, DD/MM/YYYY dates.
- Deterministic: `python -m data_generator --seed 42 --sets 8` produces byte-identical
  ground-truth JSON and PDFs with identical content (PDF metadata such as creation date may
  differ). No `datetime.now()` or unseeded randomness: all dates and random values derive
  from the seed (seed Faker too, if used).

Done when: output is reproducible, every injected error is recorded in the ground truth,
and unit tests verify that clean sets are internally consistent (line totals, VAT, totals).
