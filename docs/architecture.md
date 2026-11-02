# Architecture

## Scope

PyForge is a dependency-free Python 3.11+ library. The implemented modules are
bounded retry, JSON logging, and environment-backed configuration. HTTP
resilience is a later milestone and has no code yet.

The public API is:

```python
from pyforge import (
    JsonFormatter,
    LogContext,
    RetryPolicy,
    get_env,
    get_env_bool,
    get_env_int,
    get_logger,
    retry,
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
- `tests/test_retry.py`, `tests/test_logging.py`, and `tests/test_config.py`:
  deterministic unit tests. Retry tests inject sleep and randomness. Logging
  tests inject records and handlers. Configuration tests use `monkeypatch`.

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

## Import side effects

Importing `pyforge` imports the retry, logging, and configuration modules. It
does not configure the root logger, read environment variables, read `.env`
files, or open a network connection.

## Known limitations

- No persistent retry state, process supervision, circuit breaker, or rate limit.
- Callers must decide whether an operation is safe to repeat.
- Remote writes need their own idempotency strategy.
- Async wrappers await `sleep`. The default is `asyncio.sleep`. A blocking
  function passed as async sleep would block the event loop.
- Only `async def` functions are detected as asynchronous. A plain function
  that returns a coroutine is treated as synchronous.
- Log redaction is limited to the names, suffixes, and text patterns in the
  security notes. HTTP retries are not implemented.
- Configuration readers return the parsed value. They do not redact it. A
  caller that logs the returned string is responsible for that output.

## Further documentation

- [API reference](api-reference.md) for parameters, return values, and exceptions.
- [Security notes](security.md) for idempotency, secrets, and dependencies.
- [Changelog](../CHANGELOG.md) for the 0.1.0 alpha and unreleased work.
- [ADR 0002](decisions/0002-structured-logging.md) for the logging decision.
- [ADR 0003](decisions/0003-environment-configuration.md) for the configuration decision.
