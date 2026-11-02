# ADR-0003: Database schema: typed tables for what we query, JSONB for what we keep

- Status: accepted
- Date: 2026-11-02

## Context

Step 5 makes the pipeline persistent (PostgreSQL 17 + pgvector, SQLAlchemy 2, Alembic). Some
data is queried and summed: invoice totals per supplier, findings per document, the job
queue. Step 7's structured questions run as fixed SQL functions over it. Other data is only
stored and read back whole: Docling output, the raw LLM response, provenance maps.

## Decision

- **Typed tables** for documents, the three document types and their lines, discrepancies
  and jobs. Money is `NUMERIC(12,2)`, unit prices and quantities `NUMERIC(12,4)`, VAT rates
  `NUMERIC(5,4)`, API cost `NUMERIC(12,6)`. Supplier and buyer are inline columns (exactly
  one each per document).
- **JSONB** for parser output (`parses.data`), raw extractions (`extractions.raw`) and
  provenance. No table per nested structure we never query.
- **Separate models, explicit mapping.** SQLAlchemy rows (`backend/app/db/models.py`) and
  Pydantic domain models stay separate; `backend/app/db/mapping.py` converts by hand, and a
  round-trip test on generated documents fails if the two drift apart. A second test checks
  the Alembic migrations produce exactly the schema the models describe.
- **Raw vs corrected.** `extractions` rows are never updated (re-processing adds a version);
  human changes go to `corrections`.
- **Tenancy.** Every table has `owner_id`; uniqueness of uploads is per owner
  (`owner_id, sha256`).
- **`documents.id` is the domain `document_id`**, so findings, extractions and typed rows all
  join on one key.

## Consequences

- SQL can aggregate amounts exactly (Decimal in, Decimal out).
- Changing a nested JSON structure needs no migration; changing a typed column does.
- Inline party columns duplicate supplier names across documents; a suppliers master table
  (for VAT-number matching and fuzzy names like `ple`/`plc`) is a later addition.
