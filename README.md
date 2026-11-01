# DocuFlow AI

Document intelligence + RAG for invoices, purchase orders and delivery notes: LLM extraction,
three-way matching, deterministic discrepancy rules, cited answers, and a measured evaluation
pipeline.

> Work in progress. See [`docs/progress.md`](docs/progress.md).

## Development

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
uv run mypy backend data_generator
```
