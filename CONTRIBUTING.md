# Contributing

## Local setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

The `dev` extra includes pytest-asyncio and the `build` package. Async tests and
package builds do not need a separate install. `build` is not a runtime
dependency.

## Before opening a pull request

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=pyforge --cov-report=term-missing
python -m build
python scripts/check_distribution.py
```

Do not commit `dist/`, `build/`, virtual environments, `.coverage`, or `.env` files.

## Engineering expectations

- Add tests for new behavior and edge cases.
- Keep public APIs typed and documented.
- Avoid runtime dependencies without a clear technical reason.
- Update architecture documentation or add an ADR when changing design.
- Never commit credentials, tokens, local environment files, or private data.
- Keep pull requests focused and explain trade-offs.
