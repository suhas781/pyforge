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

`JsonFormatter` writes JSON. Importing `pyforge` or `pyforge.logging` does not
configure the root logger, attach handlers, or change log levels. Callers
attach a handler themselves.

Redaction is exact and limited. It is not a general secret scanner.

These mapping keys are replaced with `"[REDACTED]"` before serialization.
Comparison is case-insensitive, and hyphens are treated as underscores.
CamelCase is not split, so `sessionToken` is not matched.

- Exact names: `password`, `passwd`, `token`, `access_token`,
  `refresh_token`, `id_token`, `authorization`, `secret`, `api_key`, `apikey`.
- Suffixes: `_password`, `_passwd`, `_token`, `_secret`, `_api_key`,
  `_authorization`.

The same replacement is used for the whole value. Nested values under a
sensitive key are not inspected and are not emitted.

These text patterns are rewritten in messages, context strings, exception
messages, and tracebacks:

- `Authorization:` followed by an optional `Bearer` and a token becomes
  `Authorization: [REDACTED]`.
- A remaining `Bearer` token becomes `Bearer [REDACTED]`.
- `password`, `passwd`, `token`, `access_token`, `refresh_token`, `id_token`,
  `api_key`, `apikey`, or `secret`, followed by `=` or `:`, becomes
  `name=[REDACTED]`. The value runs until whitespace.

Unsupported `extra` keys are omitted from the JSON object, so a password
passed only under an unknown extra key is not written. Context fields are not
themselves sensitive names: `component="hunter2"` is logged, while
`component="password=hunter2"` matches the text pattern.

A field named `value`, `data`, or `password_policy` is not sensitive. A raw
token with no matching key or pattern is not detected. Tracebacks do not
include local variables; source lines are redacted only when they match a
pattern above.

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
