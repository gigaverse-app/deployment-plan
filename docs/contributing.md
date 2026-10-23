# Contributing

Use Python 3.12 or newer and uv:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
uv run twine check --strict dist/*
uv run python scripts/smoke_distribution.py
uv run mkdocs build --strict
```

Tests exercise public lifecycle behavior, real temporary Git repositories and HTTP transport boundaries. Keep reusable test helpers outside `test_*.py`. Add regressions before fixing bugs. Do not mock planning or receipt reduction in integration tests.

Use Conventional Commits for commits and PR titles. Open a draft early. Include the operator problem, changed behavior and validation evidence. Do not copy AGPL source from sfdx-hardis; this independent implementation learns from its documented workflow concepts.

The original generic ledger implementation and its regression tests were extracted from Gigaverse's backend. Consumer manifests and business-specific deployment policy remain in the consumer repositories.
