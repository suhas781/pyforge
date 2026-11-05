# Contributing

## Local setup

```bash
python -m venv .venv
python -m pip install --upgrade pip "setuptools>=77" wheel
python -m pip install -e ".[dev]"
```

The `dev` extra includes pytest-asyncio and the `build` package. Async tests and
package builds do not need a separate install. `build` is not a runtime
dependency. `setuptools>=77` matches the build-system requirement used by
`python -m build`.

## Before opening a pull request

```bash
ruff check .
ruff format --check .
mypy src playground scripts
pytest --cov=pyforge --cov-report=term-missing
python scripts/audit_installed_packages.py
python -m build
python scripts/check_distribution.py
```

The audit script needs network access. It reports OSV advisories for the
packages installed in the current environment. It does not prove that those
packages are free of vulnerabilities.

Do not commit `dist/`, `build/`, virtual environments, `.coverage`, or `.env` files.

## Engineering expectations

- Add tests for new behavior and edge cases.
- Keep public APIs typed and documented.
- Avoid runtime dependencies without a clear technical reason.
- Update architecture documentation or add an ADR when changing design.
- Never commit credentials, tokens, local environment files, or private data.
- Keep pull requests focused and explain trade-offs.

## License

The project license is the MIT license in `LICENSE`. `pyproject.toml` sets
`license = "MIT"` and packages that file. This repository does not contain a
contributor license agreement or another contributor contract.

A tagged release or PyPI upload is not part of a feature pull request. The
checklist is `docs/releasing.md`. The owner has to approve a release
explicitly. Merging to `main` does not publish the package.
