# API reference

This page describes the public objects implemented in version 0.1.0. Import them
from the package root:

```python
from pyforge import RetryPolicy, retry
```

`pyforge.__version__` is the string `"0.1.0"`. Private helpers in `pyforge.retry`
are not part of the public API.

## RetryPolicy

```python
RetryPolicy(
    max_attempts: int = 3,
    initial_delay: float = 0.25,
    max_delay: float = 5.0,
    multiplier: float = 2.0,
    jitter: float = 0.0,
)
```

Immutable configuration for bounded exponential backoff. Instances are frozen
and use slots, so attributes cannot be reassigned. Delays are in seconds.
`max_attempts` includes the first call. `jitter` is a fraction in `[0, 1]`;
`0` disables jitter.

| Field | Default | Accepted values |
| --- | --- | --- |
| `max_attempts` | `3` | Integer greater than or equal to 1. Booleans and non-integers are rejected. |
| `initial_delay` | `0.25` | Finite real number greater than or equal to 0. |
| `max_delay` | `5.0` | Finite real number greater than or equal to 0. It may be lower than `initial_delay`. |
| `multiplier` | `2.0` | Finite real number greater than or equal to 1. |
| `jitter` | `0.0` | Finite real number from 0 through 1. |

Invalid values raise `ValueError` when the policy is constructed.

### RetryPolicy.delay_for

```python
delay_for(failed_attempt: int, random_value: float = 0.5) -> float
```

Return the delay in seconds after a 1-based failed attempt.

```text
base = min(initial_delay * multiplier ** (failed_attempt - 1), max_delay)
factor = 1 + jitter * (2 * random_value - 1)
delay = min(max(base * factor, 0), max_delay)
```

`random_value` must be a finite number in `[0, 1]`. `failed_attempt` must be an
integer greater than or equal to 1. Exponents that overflow or are non-finite
are capped at `max_delay`. Once the base delay is already at `max_delay`,
jitter can reduce the delay but cannot increase it.

Raises `ValueError` when `failed_attempt` or `random_value` is invalid.

```python
policy = RetryPolicy(max_attempts=4, initial_delay=0.25, max_delay=2.0)
policy.delay_for(failed_attempt=1, random_value=0.5)  # 0.25
```

## retry

```python
retry(
    *,
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    sleep: Callable[[float], Any] | None = None,
    random_value: Callable[[], float] = random.random,
) -> Callable[[F], F]
```

Decorator factory for a synchronous or asynchronous callable. `asyncio.iscoroutinefunction`
selects the wrapper. Omitted `policy` uses `RetryPolicy()`. The wrapper calls
the original function with the same positional and keyword arguments and
returns its value unchanged, including values such as `0`, `False`, and `None`.

`retry_on` must be a non-empty tuple of `Exception` subclasses. Matching uses
normal Python `except` rules, so subclasses of a configured type are retried.
Any other exception propagates on the first attempt. The final matching
exception is re-raised as the same object.

`BaseException` is not caught. `asyncio.CancelledError`, `KeyboardInterrupt`,
`SystemExit`, and `GeneratorExit` propagate and are not retried. Passing
`BaseException` or another non-`Exception` type in `retry_on` raises
`TypeError` when the decorator is created. An empty tuple raises `ValueError`.

The default `retry_on=(Exception,)` retries every `Exception` subclass,
including `ValueError` and `RuntimeError`. Pass a narrower tuple.

Synchronous functions use `time.sleep` unless `sleep` is injected.
Asynchronous functions use `asyncio.sleep` unless `sleep` is injected, and
that injected callable must be awaitable. `random_value` is called once per
retry delay and must return a number in `[0, 1]`. An invalid draw raises
`ValueError` before sleep; the original operation exception remains the
context of that `ValueError`.

`functools.wraps` preserves `__name__`, `__qualname__`, `__doc__`, `__module__`,
`__annotations__`, and `__wrapped__`.

Only `async def` functions are treated as asynchronous. A plain function that
returns a coroutine is called through the synchronous wrapper.

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

Retrying a remote write can repeat its side effects. Do that only when the
operation is idempotent or the request carries an idempotency key.

## JsonFormatter

```python
JsonFormatter()
```

`logging.Formatter` that returns one JSON object and no trailing newline.
Handlers still add their own terminator. The object uses compact separators
and sorted keys. Unicode is preserved (`ensure_ascii=False`). Non-finite
floats are not emitted as `NaN` or `Infinity`.

| Field | When present | Value |
| --- | --- | --- |
| `timestamp` | always | UTC time from `LogRecord.created`, millisecond precision, `Z` suffix |
| `level` | always | `LogRecord.levelname`, including `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL` |
| `logger` | always | Logger name |
| `message` | always | Redacted message. A mapping message becomes a JSON object. Other messages are formatted with the standard `%` arguments and then redacted. |
| `request_id`, `operation`, `component` | attribute is present and not `None` | Sanitized value |
| `attempt` | attribute is a non-boolean `int` greater than or equal to 0 | That integer |
| `exception` | `exc_info` contains an exception type | Object with `type`, redacted `message`, and redacted `traceback` when a traceback exists |

Record attributes other than those fields are ignored. In particular, an
`extra` key such as `password` is not copied into the JSON object.

`format` does not add handlers and does not change the root logger.

## LogContext

```python
LogContext(
    request_id: str | None = None,
    operation: str | None = None,
    attempt: int | None = None,
    component: str | None = None,
)
```

Frozen context for `get_logger`. Unknown keyword arguments raise `TypeError`.
`request_id`, `operation`, and `component` must be strings or `None`.
`attempt` must be an integer greater than or equal to 0, or `None`. Booleans
are rejected. Invalid values raise `ValueError`.

`to_dict()` returns only the fields that were set.

## get_logger

```python
get_logger(name: str, *, context: LogContext | None = None) -> logging.LoggerAdapter
```

Return an adapter around `logging.getLogger(name)`. `name` must be a non-empty
string other than `"root"`; otherwise `get_logger` raises `ValueError`.
`context` must be a `LogContext` or `None`.

This function does not attach handlers, change propagation, or configure the
root logger. The caller configures handlers. Call-site `extra` must be a
`dict` or `None` and overrides context fields for that call. `JsonFormatter`
still drops extra keys that are not supported context fields.

```python
import logging

from pyforge import JsonFormatter, LogContext, get_logger

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = get_logger(
    "billing",
    context=LogContext(component="api", operation="charge", attempt=1),
)
logger.logger.addHandler(handler)
logger.logger.propagate = False
logger.info("charged", extra={"request_id": "req-7"})
```

## Redaction constants

`REDACTED` is `"[REDACTED]"`. `SENSITIVE_FIELD_NAMES` and
`SENSITIVE_FIELD_SUFFIXES` are the exact key rules. `CONTEXT_FIELD_NAMES` is
the exact context allowlist. The rules and their limits are in
[Security notes](security.md).
