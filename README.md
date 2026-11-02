# PyForge

**A production-minded Python engineering toolkit.**

PyForge is a small, typed Python package for reusable engineering primitives. The current code covers bounded retries, JSON logging, and environment-backed configuration. HTTP examples are a later milestone and are not implemented.

Supported Python: 3.11 and newer. The CI workflow is configured for 3.11, 3.12, and 3.13. There are no runtime dependencies.

> Status: Milestone 3 environment configuration is implemented and verified locally on Python 3.11. This is an alpha library (`0.1.0`), not a production certification and not a replacement for Tenacity, structlog, or pydantic-settings. Hosted CI for this branch has not been observed yet.

## Why PyForge exists

AI and backend systems are only as reliable as the code around them. PyForge starts with an explicit retry policy that callers opt into, with deterministic tests and a typed public API.

## Current features

- Immutable `RetryPolicy` with validated attempts, delays, multiplier, and jitter
- `@retry` for synchronous and asynchronous callables
- Retries only configured `Exception` subclasses, then re-raises the final exception unchanged
- `asyncio.CancelledError` and other `BaseException` values propagate and are not retried
- Injectable sleep and random functions so tests do not wait on real time
- `JsonFormatter` and `get_logger` for one JSON object per record, without configuring the root logger
- `get_env`, `get_env_bool`, `get_env_int`, and `get_env_float` read one variable per call, with explicit defaults, required values, and numeric bounds
- Standard-library-only runtime

## Safety

Retrying a call can repeat its side effects. Retry a remote write only when the operation is idempotent or the request carries an idempotency key. PyForge does not decide that for you. See [Security notes](docs/security.md). The parameter and exception details are in the [API reference](docs/api-reference.md).

`retry_on` defaults to `(Exception,)`, which includes ordinary failures such as `ValueError` and `RuntimeError`. Pass a narrow tuple. `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, and `asyncio.CancelledError` are not caught.

Importing `pyforge` does not configure the root logger, read environment variables, or make network calls. JSON logging redacts only the names, suffixes, and text patterns in [Security notes](docs/security.md). Configuration errors omit the stored value; the returned value itself is not redacted.

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

```python
from pyforge import get_env, get_env_bool, get_env_int

database_url = get_env("DATABASE_URL", required=True)
debug = get_env_bool("DEBUG", default=False)
port = get_env_int("PORT", default=8000, minimum=1, maximum=65535)
```

`get_env` returns the stored string. `DEBUG` accepts `true`, `1`, `yes`, `on`, `false`, `0`, `no`, and `off`. These functions do not load a `.env` file.

## Design principles

1. Explicit behavior: retries are bounded and exception-aware.
2. Testability: time and randomness are injectable.
3. Small dependencies: runtime code uses the Python standard library.
4. Typed public API: public functions and data structures are annotated.
5. No hidden magic: retry behavior is documented in `docs/architecture.md` and `docs/api-reference.md`.

## Repository structure

```text
pyforge/
├── src/pyforge/
│   ├── __init__.py
│   ├── config.py
│   ├── logging.py
│   ├── py.typed
│   └── retry.py
├── tests/test_retry.py
├── tests/test_logging.py
├── tests/test_config.py
├── docs/
│   ├── architecture.md
│   ├── api-reference.md
│   ├── security.md
│   └── decisions/
│       ├── 0001-retry-policy.md
│       ├── 0002-structured-logging.md
│       └── 0003-environment-configuration.md
├── scripts/check_distribution.py
├── .github/workflows/ci.yml
├── pyproject.toml
├── CHANGELOG.md
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
python -m build
python scripts/check_distribution.py
```

The `dev` extra declares pytest, pytest-asyncio, pytest-cov, Ruff, mypy, and the `build` frontend. Coverage is configured to fail under 90% for the `pyforge` package. `build` produces installable artifacts; the library does not import it.

## Roadmap

- [x] Package skeleton, MIT license, and pyproject metadata
- [x] Milestone 1: sync and async retry core, validation, and deterministic tests
- [x] CI workflow for Python 3.11, 3.12, and 3.13, including package build and artifact checks
- [x] Milestone 5: API reference, security notes, changelog, and distribution validation
- [x] Milestone 2: structured JSON logging
- [x] Milestone 3: environment-backed configuration helpers
- [ ] Milestone 4: optional HTTP resilience example
- [ ] Milestone 6: tagged release after owner approval

## Limitations

- No distributed coordination, persistent retry state, circuit breaker, or rate limiter.
- Jitter is a symmetric fraction around the capped backoff. It cannot extend a delay past `max_delay`, so the interval is not symmetric once the cap is hit.
- Async sleep must be awaitable. Injecting a blocking sleep function would block the event loop.
- HTTP retries are not implemented. Configuration readers do not load `.env` files or cache values.
- Log redaction covers only the field names, suffixes, and text patterns in `docs/security.md`. A value that does not match those rules is not detected. Configuration functions return secrets as stored and only keep them out of error messages.
- No benchmark numbers are published.
- Hosted CI for this configuration branch has not been observed yet. Python 3.12 and 3.13 were not run locally.

## License

MIT. See [LICENSE](LICENSE).
