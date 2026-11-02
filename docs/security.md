# Security notes

PyForge 0.1.0 is a small retry library. These notes describe the controls that
exist in this version. They are not a security certification, threat model, or
guarantee that a caller is safe from duplicate side effects.

## Idempotency

The retry decorator repeats a failed call. A remote write, payment, or other
non-idempotent operation can run more than once. PyForge does not create
idempotency keys, compare responses, or decide whether an operation is safe to
repeat. Callers have to do that before they configure `retry_on`.

## Exception and cancellation boundaries

The wrapper catches only the configured `Exception` subclasses. It does not
catch `BaseException`. Cancellation (`asyncio.CancelledError`), keyboard
interrupts, and system exit therefore propagate instead of being retried.

That behavior depends on the caller passing real `Exception` types and on
CPython's exception hierarchy. It does not stop a caller from retrying a broad
tuple such as `(Exception,)`. The default is that broad tuple; narrow it.

## Secrets and local files

The runtime package does not read environment variables, `.env` files, or
credential stores. Importing `pyforge` does not configure logging and does not
open a network connection.

`.env` files are gitignored. `.env.example` contains only a comment and no
credentials. Do not commit tokens, passwords, private keys, or customer data.
The distribution check rejects wheel or sdist paths that look like `.env`,
`.pem`, `.key`, or `id_rsa` files. That check is a packaging guard, not a scan
of file contents and not a promise that every secret pattern will be found.

## Logging

Structured logging is not implemented. This version has no redaction filter
because it does not write log records. Callers that log retries themselves
should keep authorization headers, passwords, tokens, and raw sensitive
payloads out of those logs. A future logging module must not turn on the root
logger at import time.

## Dependencies

The installed library has no runtime dependencies. Development tools are
optional: pytest, pytest-asyncio, pytest-cov, Ruff, mypy, and the `build`
frontend. `build` is used to produce artifacts; application code does not
import it.

Minimum versions are declared in `pyproject.toml`. They are not hash-pinned.
GitHub Actions are pinned to major tags (`actions/checkout@v4` and
`actions/setup-python@v5`), not to commit SHAs. Review any new dependency
before adding it, and do not add a runtime dependency for a feature that the
standard library already covers.

## Package contents

The wheel is the installable library: `pyforge`, its `py.typed` marker, and
the MIT license. Tests are not part of the wheel. Installing the package does
not enable telemetry or background work.
