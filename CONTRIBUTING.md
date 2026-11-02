# Contributing

## Local setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

`pytest-asyncio` is part of the `dev` extra. Async tests do not need a separate install.

## Before opening a pull request

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=pyforge --cov-report=term-missing
python -m pip install build
python -m build
```

## Engineering expectations

- Add tests for new behavior and edge cases.
- Keep public APIs typed and documented.
- Avoid runtime dependencies without a clear technical reason.
- Update architecture documentation or add an ADR when changing design.
- Never commit credentials, tokens, local environment files, or private data.
- Keep pull requests focused and explain trade-offs.
