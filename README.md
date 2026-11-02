# PyForge

**A production-minded Python engineering toolkit.**

PyForge is a small, typed Python package for reusable engineering primitives. The current release scope is bounded retries for synchronous and asynchronous callables. Structured logging, configuration helpers, and HTTP examples are later milestones and are not implemented.

Supported Python: 3.11 and newer. The CI workflow is configured for 3.11, 3.12, and 3.13. There are no runtime dependencies.

> Status: Milestone 1 retry core. This is an alpha library (`0.1.0`), not a production certification and not a replacement for Tenacity.

## Why PyForge exists

AI and backend systems are only as reliable as the code around them. PyForge starts with an explicit retry policy that callers opt into, with deterministic tests and a typed public API.

## Current features

- Immutable `RetryPolicy` with validated attempts, delays, multiplier, and jitter
- `@retry` for synchronous and asynchronous callables
- Retries only configured `Exception` subclasses, then re-raises the final exception unchanged
- `asyncio.CancelledError` and other `BaseException` values propagate and are not retried
- Injectable sleep and random functions so tests do not wait on real time
- Standard-library-only runtime

## Safety

Retrying a call can repeat its side effects. Retry a remote write only when the operation is idempotent or the request carries an idempotency key. PyForge does not decide that for you.

`retry_on` defaults to `(Exception,)`, which includes ordinary failures such as `ValueError` and `RuntimeError`. Pass a narrow tuple. `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, and `asyncio.CancelledError` are not caught.

Importing `pyforge` does not configure logging and does not make network calls.

## Quick start

```bash
git clone https://github.com/suhas781/pyforge.git
cd pyforge
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

## Example

```python
from pyforge import RetryPolicy, retry


@retry(
    policy=RetryPolicy(
        max_attempts=4,
        initial_delay=0.25,
        max_delay=2.0,
        multiplier=2.0,
        jitter=0.1,
    ),
    retry_on=(TimeoutError,),
)
def fetch_remote_data() -> dict[str, str]:
    return {"status": "ok"}
```

`max_attempts` includes the first call. After the last matching failure, the original exception is raised with its type and message unchanged. Tests should inject `sleep` and `random_value` instead of waiting on `time.sleep` or `asyncio.sleep`.

## Design principles

1. Explicit behavior: retries are bounded and exception-aware.
2. Testability: time and randomness are injectable.
3. Small dependencies: runtime code uses the Python standard library.
4. Typed public API: public functions and data structures are annotated.
5. No hidden magic: retry behavior is documented in `docs/architecture.md`.

## Repository structure

```text
pyforge/
├── src/pyforge/
│   ├── __init__.py
│   ├── py.typed
│   └── retry.py
├── tests/test_retry.py
├── docs/
│   ├── architecture.md
│   └── decisions/0001-retry-policy.md
├── .github/workflows/ci.yml
├── pyproject.toml
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

## Development commands

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=pyforge --cov-report=term-missing
python -m pip install build
python -m build
```

The `dev` extra declares pytest, pytest-asyncio, pytest-cov, Ruff, and mypy. Coverage is configured to fail under 90% for the `pyforge` package. `build` is only needed to produce an installable artifact; it is not a runtime or test dependency.

## Roadmap

- [x] Package skeleton, MIT license, and pyproject metadata
- [x] Milestone 1: sync and async retry core, validation, and deterministic tests
- [x] CI workflow for Python 3.11, 3.12, and 3.13
- [ ] Milestone 2: structured logging
- [ ] Milestone 3: environment-backed configuration helpers
- [ ] Milestone 4: optional HTTP resilience example
- [ ] Milestone 5: docs and CI hardening beyond the retry core
- [ ] Milestone 6: tagged release after owner approval

## Limitations

- No distributed coordination, persistent retry state, circuit breaker, or rate limiter.
- Jitter is a symmetric fraction around the capped backoff. It cannot extend a delay past `max_delay`, so the interval is not symmetric once the cap is hit.
- Async sleep must be awaitable. Injecting a blocking sleep function would block the event loop.
- Logging, configuration helpers, secret redaction, and HTTP retries are not implemented.
- No benchmark numbers are published.

## License

MIT. See [LICENSE](LICENSE).
