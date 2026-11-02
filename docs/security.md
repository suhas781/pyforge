# Security notes

PyForge 0.1.0 is a small retry, logging, configuration, and HTTP-decision
library. These notes describe the controls that exist in this version. They
are not a security certification, threat model, or guarantee that a caller is
safe from duplicate side effects.

## Idempotency

The retry decorator repeats a failed call. A remote write, payment, or other
non-idempotent operation can run more than once. PyForge does not create
idempotency keys, compare responses, or prove that a server processed a
request once.

`retry_http` narrows that choice for HTTP. It retries idempotent methods when
the status or transport exception is eligible. `POST`, `PATCH`, and other
non-idempotent methods are not retried unless `allow_unsafe_method=True`. The
flag is the caller's statement that an idempotency key, or an equivalent
server guarantee, is already in place. The library does not generate the key,
send the header, or check that the server honored it.

A client timeout is not evidence that the server did nothing. Retrying after
a timeout can apply the same POST twice when no idempotency guarantee exists.
Nothing in this package provides exactly-once execution.

## Retry events

`RetryEvent` records the event type, attempt, maximum attempts, delay, and
exception class name. It does not store the exception object, the exception
message, response bodies, or headers. `retry_http` events therefore name
`RetryableHTTPStatus` rather than copying a transport error that might contain
a URL or credential.

An `Exception` raised by an observer is discarded. That keeps a metrics
callback from hiding the application's timeout or returning a failure after
the operation succeeded. The discarded exception is not logged. `BaseException`
from the observer still propagates. PyForge does not connect these events to
a metrics backend or a tracer.

## Exception and cancellation boundaries

The wrapper catches only the configured `Exception` subclasses. It does not
catch `BaseException`. Cancellation (`asyncio.CancelledError`), keyboard
interrupts, and system exit therefore propagate instead of being retried.

That behavior depends on the caller passing real `Exception` types and on
CPython's exception hierarchy. It does not stop a caller from retrying a broad
tuple such as `(Exception,)`. The default for `retry` is that broad tuple;
narrow it. `retry_http` defaults to `TimeoutError` and `ConnectionError`.

## Secrets and local files

Importing `pyforge` does not read environment variables, `.env` files, or
credential stores, and it does not configure logging or open a network
connection. The HTTP helpers do not send requests. `RetryableHTTPStatus`
records the method, status code, and exception class name only; it does not
copy a response body or the original exception message. `get_env`,
`get_env_bool`, `get_env_int`, and `get_env_float` read one `os.environ`
entry when called. They do not load `.env` files and they do not write to
`os.environ`.

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

## Environment values

Configuration errors may include the variable name, the expected type, and the
numeric bounds. They do not include the stored value or the default. The
exception `__cause__` is left unset, so a parser error cannot attach the raw
text. The readers do not log.

That is not a redaction of the return value. `get_env("DATABASE_URL")` returns
the URL as stored. If the caller logs that string, `JsonFormatter` applies
only the text patterns above. A URL containing `password=supersecret` matches
the assignment pattern. A URL that is only a raw token does not.

The readers also do not inspect whether a variable name looks sensitive.
`get_env("API_TOKEN")` returns the token. Callers should avoid logging it.

## Process-local cache

`MemoryCache` keeps values in the process that created it. Those values are
ordinary references. A cached token or profile stays readable to other code
in the same process until the entry expires, is evicted, is deleted, or the
process exits. The cache does not encrypt values, and it does not redact
them. Do not log a cached value unless it is already safe to log.

The `KeyError` for a missing or expired key says that the entry is missing or
expired. It does not include the key. Callers should still avoid putting raw
secrets in keys, because key equality and hashing run inside the cache and a
custom key type could reveal itself.

Expiration and eviction are local. Another process, host, or later restart
does not observe them. Do not use the cache as the only copy of an
authorization decision that must be revoked everywhere at once.

The cache does not start a thread and does not read the environment. A clock
callback runs without the cache lock. Key hashing and equality run with the
lock held, so a key that calls back into the same cache can deadlock.

## Test helpers

`pyforge.testing` is part of the installable package so application tests can
import it. Importing `pyforge` does not import it, and the helpers do not
patch `time.sleep`, `asyncio.sleep`, or the environment on import.

`temporary_env` writes the process environment. A value placed there is
readable by every thread until the block exits. The helper restores the
previous value, including absence, when the block returns or raises. It does
not log the value, and its errors do not include the name or the value. A
name that the block sets, and that was not listed in the mapping, is left
behind. Do not use the helper as a secret store, and do not run two
environment blocks on the same names at the same time.

`FakeClock`, the recording sleepers, `CallCount`, and `FailThenReturn` keep
state on the instance. `FailThenReturn` raises an exception constructed with
no arguments, so the helper does not store an exception message.

## Dependencies

The installed library has no runtime dependencies. Development tools are
optional: pytest, pytest-asyncio, pytest-cov, Ruff, mypy, and the `build`
frontend. `build` is used to produce artifacts; application code does not
import it.

Minimum versions are declared in `pyproject.toml`. They are not hash-pinned.
GitHub Actions are pinned to major tags (`actions/checkout@v4` and
`actions/setup-python@v5`), not to commit SHAs. This repository does not run
`pip-audit`, `safety`, or another vulnerability database in CI. Absence of a
scanner result is not a claim that those tools are free of issues. Review any
new dependency before adding it, and do not add a runtime dependency for a
feature that the standard library already covers.

CI does not publish artifacts. A later upload is a separate owner decision
described in the release checklist.

## Package contents

The wheel is the installable library: `pyforge`, its `py.typed` marker, and
the MIT license. Tests are not part of the wheel. Installing the package does
not enable telemetry or background work.
