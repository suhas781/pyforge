# Architecture

## Scope

PyForge is a dependency-free Python 3.11+ library. The implemented modules are
bounded retry, JSON logging, environment-backed configuration, HTTP retry
decisions, retry events, a process-local memory cache, and deterministic
test helpers. There is no HTTP client in the package.

The public API is:

```python
from pyforge import (
    CacheStats,
    JsonFormatter,
    LogContext,
    MemoryCache,
    RetryPolicy,
    get_env,
    get_env_bool,
    get_env_int,
    get_logger,
    retry,
    retry_http,
    should_retry_http,
)
```

`pyforge.__version__` is `0.1.0`.

## Module boundaries

- `RetryPolicy`: frozen, slotted configuration and `delay_for`.
- `retry`: decorator factory. It selects a sync or async wrapper with
  `asyncio.iscoroutinefunction`.
- `JsonFormatter`: one JSON object per record, using the standard `logging`
  types. It does not attach handlers.
- `LogContext` and `get_logger`: optional `request_id`, `operation`,
  `attempt`, and `component` values. Unknown context keywords are rejected.
  Unknown `extra` keys stay off the JSON object.
- `get_env`, `get_env_bool`, `get_env_int`, and `get_env_float`: read one
  environment variable when called. They do not cache it or load `.env` files.
- `should_retry_http`, `raise_for_retryable_status`, and `retry_http`: decide
  whether an HTTP status or transport exception may be retried, then reuse
  `retry` for the attempt limit and delay.
- `RetryEvent` and the optional `observer`: report scheduled retries, later
  success, and exhausted attempts. There is no global observer.
- `MemoryCache`: one instance owns an ordered mapping, a lock, and counters.
  There is no process-wide cache.
- `pyforge.testing`: fake clock, recorded sleep, scripted calls, and a
  temporary environment block. The package root does not import it.
- `tests/test_retry.py`, `tests/test_logging.py`, `tests/test_config.py`,
  `tests/test_http.py`, `tests/test_observe.py`, `tests/test_cache.py`, and
  `tests/test_testing.py`: deterministic unit tests.
  Retry and HTTP tests inject sleep and randomness. Logging tests inject
  records and handlers. Configuration tests use `monkeypatch`. HTTP tests use
  fakes and do not open sockets. Cache tests inject a monotonic clock and do
  not sleep.

Tests stay in `tests/` until more than one module needs a split layout. There
is no integration suite yet.

## Retry lifecycle

1. Validate the policy at construction and `retry_on` when the decorator is
   created.
2. Call the wrapped function with the original positional and keyword
   arguments.
3. On success, return the value immediately, including falsy values.
4. If the exception is not an instance of a configured type, propagate it
   immediately. Subclasses of a configured type match, because that is
   Python's `except` behavior.
5. If attempts remain, compute one delay, call the injected random function
   once, then sleep. `max_attempts` includes the first call.
6. On the final matching failure, re-raise that exception object unchanged.
7. Each wrapper keeps its own attempt counter. Policies are immutable and can
   be reused.

`functools.wraps` preserves the wrapped callable's name, qualname, docstring,
module, annotations, and `__wrapped__`.

## Delay calculation

After failed attempt `n` (1-based), with `random_value` in `[0, 1]`:

```text
base = min(initial_delay * multiplier ** (n - 1), max_delay)
factor = 1 + jitter * (2 * random_value - 1)
delay = min(max(base * factor, 0), max_delay)
```

`jitter` of `0` leaves the delay at `base`. `random_value` of `0` selects the
lower factor `1 - jitter`; `1` selects `1 + jitter`. A zero `initial_delay`
or zero `max_delay` is valid and yields a zero delay. Exponents that overflow
or become non-finite are treated as larger than `max_delay` and then capped.
`max_delay` may be lower than `initial_delay`; the cap still applies.

Once `base` is already `max_delay`, positive jitter cannot increase the delay
further. Negative jitter can still reduce it. The capped interval is therefore
not symmetric.

## Exception and cancellation behavior

The wrapper uses `except retry_on` and nothing broader. It does not catch
`BaseException`.

These propagate on the first occurrence and do not sleep or retry:

- `asyncio.CancelledError`, whether the operation raises it or the task is
  cancelled while the operation or the awaitable sleep is in progress
- `KeyboardInterrupt`
- `SystemExit`
- `GeneratorExit`
- any other `BaseException`

`retry_on` must be a non-empty tuple of `Exception` subclasses. `BaseException`,
`KeyboardInterrupt`, and `CancelledError` are rejected at decoration time.
The default tuple is `(Exception,)`. Callers should narrow it so bugs such as
`TypeError` are not retried.

An invalid `random_value` raises `ValueError` before sleep. That `ValueError`
chains the original operation exception as its context.

## Validation

`RetryPolicy` rejects non-integers and booleans for `max_attempts`, and
non-real, non-finite, or out-of-range values for the numeric fields:

| Field | Rule |
| --- | --- |
| `max_attempts` | integer, minimum 1, default 3 |
| `initial_delay` | finite seconds, minimum 0, default 0.25 |
| `max_delay` | finite seconds, minimum 0, default 5 |
| `multiplier` | finite number, minimum 1, default 2 |
| `jitter` | finite fraction in `[0, 1]`, default 0 |

## Structured logging

`JsonFormatter.format` builds a dictionary with `timestamp`, `level`,
`logger`, and `message`, then adds context and exception fields when they are
usable. Timestamps come from `LogRecord.created` and are formatted in UTC.
The formatter has no mutable buffers. `get_logger` returns a
`logging.LoggerAdapter` and leaves handler configuration to the caller.

Mappings are sanitized before `json.dumps`. Sensitive keys use the public
name and suffix lists. Strings use the patterns in the security notes.
Cycles become `"<circular>"`. Values that JSON cannot represent become
`"<non-finite>"` or `"<unserializable TypeName>"`, using the type name rather
than `repr`, so a secret stored only in `repr` is not emitted. Nested
sanitizing stops after 20 levels.

## Environment configuration

Each reader validates its arguments, then reads `os.environ` once. A later
call reads the environment again. Nothing is written back.

`get_env` returns the stored string. `get_env_bool`, `get_env_int`, and
`get_env_float` strip surrounding whitespace before parsing. Accepted
booleans are `true`, `1`, `yes`, `on`, `false`, `0`, `no`, and `off`, compared
without case. Integers are base-10 digit strings with an optional sign.
Floats also allow a decimal point and an exponent. `NaN` and infinities are
rejected. Numeric bounds are inclusive.

Missing required variables raise `MissingEnvironmentError`. A required
`get_env` value of `""` does too. Blank text given to a typed reader is
`InvalidEnvironmentError`, not a missing value. Numbers outside the bounds
raise `OutOfRangeEnvironmentError`. Messages name the variable and the
expected type or bounds, and omit the stored value.

## HTTP retry decisions

`retry_http` validates the method and exception tuple, then decorates the
callable with the existing `retry` helper. The only exception that helper
retries is `RetryableHTTPStatus`, so the attempt limit, jitter, injected
sleep, and cancellation behavior stay in one place.

A transport exception is translated into `RetryableHTTPStatus` only when the
method is idempotent or `allow_unsafe_method` is true, and the exception
matches `retry_on`. The default tuple is `TimeoutError` and `ConnectionError`.
The translated message keeps the class name and drops the original text.

Status codes are not read from the return value, because PyForge has no
response type. The callable calls `raise_for_retryable_status` with the status
it received. The default retryable codes are 408, 429, 500, 502, 503, and 504.

Idempotent methods follow RFC 9110: GET, HEAD, OPTIONS, PUT, DELETE, and
TRACE. POST and PATCH are not retried unless the caller opts in. The opt-in
does not send an `Idempotency-Key`; the caller must already have done that on
the client. There is no timeout parameter. The transport owns the deadline. A
client timeout does not prove the server ignored the request, and a later
attempt can duplicate a write.

## Retry observability

`retry` accepts an optional synchronous `observer`. The same callback is
forwarded by `retry_http` into that one decorator, so a retry produces one
set of events rather than two.

The engine emits:

1. `scheduled` after a matching failure when another attempt remains, before
   sleep. `attempt` is the attempt that failed. `delay` is the value passed
   to sleep. `exception_type` is `type(exc).__name__`.
2. `succeeded` only when a later attempt returns. The first attempt does not
   emit it. `delay` and `exception_type` are `None`.
3. `exhausted` when the final matching attempt fails, before the original
   exception is re-raised. `attempt` equals `max_attempts`. There is no delay.

A non-matching exception, including cancellation, emits neither `scheduled`
nor `exhausted`. An `Exception` from the observer is discarded after the event
was accepted by the callback's own failure. The attempt counter and the
application result stay unchanged. `KeyboardInterrupt`, `SystemExit`, and
`CancelledError` from the observer propagate.

HTTP lifecycle events name `RetryableHTTPStatus`. They do not repeat the
decision made by `should_retry_http`, and they do not include response bodies,
headers, or exception messages.

## In-memory cache

`MemoryCache` is a synchronous mapping with three extra rules: a maximum
number of live entries, an optional monotonic TTL, and LRU eviction.

`set` records the clock reading for that call. The entry expires when a later
reading is greater than or equal to that time plus `ttl`. `get` does not
extend the TTL. `ttl=None` does not expire. `ttl=0` is already expired and is
not stored. A negative, boolean, non-numeric, or non-finite TTL is rejected.

Expiration is lazy. `get`, `set`, `delete`, `in`, and `len` drop expired
entries before they do their own work. Nothing scans the cache on a
background thread.

When a new key would exceed `max_entries`, the least recently used live entry
is removed and `evictions` increases by one. `get` and a replacement `set`
move the key to the newest position. `in` does not. Deleting, clearing, or
expiring an entry is not an eviction.

The clock is read before the instance lock is acquired. The mapping lookup
still hashes and compares keys while the lock is held. A key's `__hash__` or
`__eq__` must not call back into the same cache.

Returned values are the stored objects. The cache does not copy them and does
not treat an exception object as a failure. A stored `None` is a hit. A
missing or expired key raises `KeyError` unless `get` was given a default.
That error text does not include the key.

`stats` returns a frozen snapshot. `clear` drops entries and leaves the
counters unchanged. `reset_stats` zeros the counters and leaves the entries
unchanged.

## Test helpers

`pyforge.testing` is imported by tests. Production code can keep importing
`pyforge` without loading it.

`FakeClock` starts at a finite number and moves only when `advance` is called.
`ClockedCache` passes that clock to `MemoryCache`. `RecordingSleeper` is the
synchronous `retry` sleep callable. `AsyncRecordingSleeper` is the separate
awaitable form. Neither waits. `CallCount` and `FailThenReturn` keep their
counts on the instance. `FailThenReturn` constructs its exception type with
no arguments, so the exception has no message.

`temporary_env` writes only the names in its mapping. On exit it restores
each of those names to its previous value, or removes it if it was absent.
An empty string is restored as an empty string. A name created inside the
block and omitted from the mapping stays set. The helper validates the
mapping before it changes `os.environ`.

## Import side effects

Importing `pyforge` imports the retry, logging, configuration, HTTP decision,
observability, and cache modules. It does not import `pyforge.testing`,
configure the root logger, read environment variables, read `.env` files,
register an observer, start a thread, or open a network connection.

## Known limitations

- No persistent retry state, process supervision, circuit breaker, or rate limit.
- Callers must decide whether an operation is safe to repeat.
- Remote writes need their own idempotency strategy.
- Async wrappers await `sleep`. The default is `asyncio.sleep`. A blocking
  function passed as async sleep would block the event loop.
- Only `async def` functions are detected as asynchronous. A plain function
  that returns a coroutine is treated as synchronous.
- Log redaction is limited to the names, suffixes, and text patterns in the
  security notes.
- Configuration readers return the parsed value. They do not redact it. A
  caller that logs the returned string is responsible for that output.
- HTTP decisions do not send requests or enforce timeouts. They do not make a
  POST exactly once. A method is classified only by its name, so a GET that
  the server implements with side effects is still treated as idempotent.
- Observers are not a metrics or tracing system. A discarded observer
  exception is not logged, because the engine does not configure logging.
- `MemoryCache` is process memory. It is not a shared or durable store.
  `max_entries` does not limit bytes. A backwards clock jump keeps entries
  alive until a later reading reaches their expiration time. Check-then-set
  across two calls is not one atomic operation.
- `temporary_env` is process-global for the names it changes. It does not
  isolate those names from other threads. `FakeClock` does not track the
  system monotonic clock.

## Further documentation

- [API reference](api-reference.md) for parameters, return values, and exceptions.
- [Security notes](security.md) for idempotency, secrets, and dependencies.
- [Changelog](../CHANGELOG.md) for the 0.1.0 alpha and unreleased work.
- [Release checklist](releasing.md) for a later tag and PyPI upload.
- [ADR 0002](decisions/0002-structured-logging.md) for the logging decision.
- [ADR 0003](decisions/0003-environment-configuration.md) for the configuration decision.
- [ADR 0004](decisions/0004-http-resilience.md) for the HTTP retry decision.
- [ADR 0005](decisions/0005-retry-observability.md) for the observer decision.
- [ADR 0006](decisions/0006-in-memory-cache.md) for the cache decision.
- [ADR 0007](decisions/0007-testing-utilities.md) for the testing-helper decision.
- [ADR 0008](decisions/0008-release-readiness.md) for the decision not to publish automatically.
