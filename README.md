# DocuFlow AI

Document intelligence + RAG for invoices, purchase orders and delivery notes: LLM extraction,
three-way matching, deterministic discrepancy rules, cited answers, and a measured evaluation
pipeline.

> Work in progress. See [`docs/progress.md`](docs/progress.md).

## Development

PDF rendering uses WeasyPrint, which needs Pango. On macOS: `brew install pango`.

```
cp .env.example .env            # then fill in ANTHROPIC_API_KEY
docker compose up -d db
uv sync
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn backend.app.api.main:app --reload   # http://localhost:8000/docs
uv run --env-file .env python -m backend.app.worker               # processes uploads
uv run pytest
uv run ruff check . && uv run ruff format .
uv run mypy backend data_generator eval
uv run python -m data_generator --seed 42 --sets 8   # writes data_generator/output/
```
