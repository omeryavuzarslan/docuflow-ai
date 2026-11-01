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
