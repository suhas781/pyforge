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
    observer: RetryObserver | None = None,
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

`observer`, when passed, is a synchronous callable taking one `RetryEvent`.
It runs before sleep for `scheduled`, after a later attempt returns for
`succeeded`, and before the original exception is re-raised for `exhausted`.
A first-attempt success does not call it. An `Exception` from the observer is
discarded. `BaseException` from the observer propagates. A non-callable
observer raises `TypeError` when the decorator is created. There is no global
observer.

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

## Environment configuration

These functions read `os.environ` on each call. They do not cache values,
load `.env` files, or modify the process environment. Importing `pyforge` does
not read environment variables.

Names are used as stored. Windows environment lookup is case-insensitive;
POSIX lookup is case-sensitive. PyForge does not normalize names.

`required=True` and `default` cannot be used together. That raises
`ValueError`. A non-string name raises `TypeError`. An empty name raises
`ValueError`. `required` must be a boolean.

```python
from pyforge import get_env, get_env_bool, get_env_int

database_url = get_env("DATABASE_URL", required=True)
debug = get_env_bool("DEBUG", default=False)
port = get_env_int("PORT", default=8000, minimum=1, maximum=65535)
```

### get_env

```python
get_env(name: str, *, default: str | None = None, required: bool = False) -> str | None
```

Returns the stored string unchanged, including surrounding whitespace. A
missing optional variable returns `default`, or `None` when no default was
passed. `MissingEnvironmentError` is raised when a required variable is unset
or set to exactly `""`. A required whitespace-only value is returned as stored.
The default, when passed, must be a string; otherwise
`InvalidEnvironmentError` is raised before the lookup.

### get_env_bool

```python
get_env_bool(name: str, *, default: bool | None = None, required: bool = False) -> bool | None
```

Surrounding whitespace is removed and the remaining text is compared
case-insensitively.

| Result | Accepted text |
| --- | --- |
| `True` | `true`, `1`, `yes`, `on` |
| `False` | `false`, `0`, `no`, `off` |

Any other text, including a blank value, raises `InvalidEnvironmentError`.
A missing variable uses the same default and required rules as `get_env`.
The default must be `True` or `False`, not `1`, `0`, or a string.

### get_env_int

```python
get_env_int(
    name: str,
    *,
    default: int | None = None,
    required: bool = False,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None
```

Surrounding whitespace is removed. The text must be an optional `+` or `-`
followed by decimal digits. `007` is accepted and parsed as `7`. Decimal
points, exponents, underscores, and other bases are rejected with
`InvalidEnvironmentError`.

`minimum` and `maximum` are inclusive. A value outside them raises
`OutOfRangeEnvironmentError`. The bounds must be integers; booleans are
rejected with `TypeError`. If `minimum` is greater than `maximum`, the call
raises `ValueError`.

Defaults follow the same integer and bounds rules. `True` and `False` are
rejected because they are not integers here. A bad default raises before the
environment is read. A present variable replaces the default.

### get_env_float

```python
get_env_float(
    name: str,
    *,
    default: float | int | None = None,
    required: bool = False,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
) -> float | None
```

Surrounding whitespace is removed. Decimal numbers and scientific notation
such as `1e-3` are accepted. `NaN`, positive and negative infinity, overflow
to infinity, underscores, and other non-numeric text raise
`InvalidEnvironmentError`. Integer defaults are returned as `float` values.
Bounds are inclusive and must be finite numbers. Non-finite bounds raise
`ValueError`.

### Configuration exceptions

| Exception | When | Base |
| --- | --- | --- |
| `MissingEnvironmentError` | A required variable is unset, or a required `get_env` value is `""`. | `Exception` |
| `InvalidEnvironmentError` | The text or default cannot be parsed as the requested type. | `ValueError` |
| `OutOfRangeEnvironmentError` | A parsed number or numeric default is outside the inclusive bounds. | `ValueError` |

`OutOfRangeEnvironmentError` is not a subclass of `InvalidEnvironmentError`.
Catch `ValueError` to handle both. Messages include the variable name and the
expected type or bounds. They do not include the environment value or the
default value.

## HTTP retry decisions

PyForge does not send HTTP requests and does not set a socket timeout. Configure
the timeout on the client that performs the call. A timeout means the client
stopped waiting. It does not mean the server skipped the request. Retrying can
repeat a side effect. This is not an exactly-once guarantee.

`IDEMPOTENT_HTTP_METHODS` is `DELETE`, `GET`, `HEAD`, `OPTIONS`, `PUT`, and
`TRACE`. `POST`, `PATCH`, `CONNECT`, and any other method are not idempotent.
`DEFAULT_RETRYABLE_STATUS_CODES` is `408`, `429`, `500`, `502`, `503`, and
`504`. `DEFAULT_RETRYABLE_HTTP_EXCEPTIONS` is `(TimeoutError, ConnectionError)`.

### is_idempotent_method

```python
is_idempotent_method(method: str) -> bool
```

Comparison strips surrounding whitespace and ignores case. A non-string raises
`TypeError`. An empty or non-alphabetic token raises `ValueError`.

### is_retryable_status

```python
is_retryable_status(
    status_code: int,
    *,
    retryable_statuses: Collection[int] | None = None,
) -> bool
```

`None` uses the default set. An empty collection matches nothing. Status codes
must be integers from 100 to 599. Booleans are rejected.

### should_retry_http

```python
should_retry_http(
    method: str,
    *,
    status_code: int | None = None,
    exception: BaseException | None = None,
    allow_unsafe_method: bool = False,
    retryable_statuses: Collection[int] | None = None,
    retry_on: tuple[type[Exception], ...] = DEFAULT_RETRYABLE_HTTP_EXCEPTIONS,
) -> bool
```

Pass a status code or an exception, not both and not neither. The result is
`False` for a non-idempotent method unless `allow_unsafe_method` is `True`.
That flag does not create an idempotency key. It records that the caller
already has one, or an equivalent guarantee. Exceptions match `retry_on` by
`isinstance`, including subclasses. `CancelledError`, `KeyboardInterrupt`, and
`SystemExit` cannot be placed in `retry_on`.

### raise_for_retryable_status

```python
raise_for_retryable_status(
    method: str,
    status_code: int,
    *,
    allow_unsafe_method: bool = False,
    retryable_statuses: Collection[int] | None = None,
) -> None
```

Raises `RetryableHTTPStatus` when `should_retry_http` is true for that status.
Otherwise it returns `None`. A 404 is not turned into a success or a failure
by this function.

### retry_http

```python
retry_http(
    *,
    method: str,
    policy: RetryPolicy | None = None,
    allow_unsafe_method: bool = False,
    retryable_statuses: Collection[int] | None = None,
    retry_on: tuple[type[Exception], ...] = DEFAULT_RETRYABLE_HTTP_EXCEPTIONS,
    sleep: Callable[[float], Any] | None = None,
    random_value: Callable[[], float] = random.random,
    observer: RetryObserver | None = None,
) -> Callable[[F], F]
```

Uses the existing `retry` decorator and `RetryPolicy`. There is no second
backoff implementation and no timeout argument. `allow_unsafe_method` here
applies only to transport exceptions caught by the decorator. Status checks
inside the function use the flag passed to `raise_for_retryable_status`.

`observer` is passed through to `retry` once. `retry_http` does not emit a
second event. Those events use `exception_type="RetryableHTTPStatus"` because
the transport error is translated before the retry loop. `should_retry_http`
does not emit events; it only answers the decision.

When a transport exception is eligible, the decorator raises
`RetryableHTTPStatus` with `error_type` set to the exception class name. The
message does not copy the original text. After the last attempt, that signal
is re-raised. `BaseException` values that are not in `retry_on` propagate on
the first occurrence.

```python
from pyforge import RetryPolicy, raise_for_retryable_status, retry_http


@retry_http(method="GET", policy=RetryPolicy(max_attempts=3))
def fetch(url: str) -> int:
    response = client.get(url, timeout=2.0)
    raise_for_retryable_status("GET", response.status_code)
    return response.status_code


@retry_http(method="POST", allow_unsafe_method=True, policy=RetryPolicy(max_attempts=2))
def create(url: str, body: bytes, idempotency_key: str) -> int:
    response = client.post(
        url,
        data=body,
        timeout=2.0,
        headers={"Idempotency-Key": idempotency_key},
    )
    raise_for_retryable_status("POST", response.status_code, allow_unsafe_method=True)
    return response.status_code
```

`client` is the caller's HTTP library. The `timeout` arguments above belong to
that library. The idempotency key is also the caller's. PyForge does not send
either one.

### RetryableHTTPStatus

```python
RetryableHTTPStatus(
    method: str,
    *,
    status_code: int | None = None,
    error_type: str | None = None,
)
```

Provide exactly one of `status_code` or `error_type`. `error_type` must be an
identifier, such as `TimeoutError`. The exception attributes are `method`,
`status_code`, and `error_type`.

## RetryEvent

```python
class RetryEventType(StrEnum):
    SCHEDULED = "scheduled"
    SUCCEEDED = "succeeded"
    EXHAUSTED = "exhausted"


RetryEvent(
    event_type: RetryEventType,
    attempt: int,
    max_attempts: int,
    delay: float | None = None,
    exception_type: str | None = None,
)
```

`RetryObserver` is `Callable[[RetryEvent], object]`. The return value is
ignored.

| `event_type` | When | `attempt` | `delay` | `exception_type` |
| --- | --- | --- | --- | --- |
| `scheduled` | A matching failure will be retried | The attempt that failed, and less than `max_attempts` | Seconds about to be passed to sleep | Exception class name |
| `succeeded` | A later attempt returned | The successful attempt, at least 2 | `None` | `None` |
| `exhausted` | The final attempt failed | Equal to `max_attempts` | `None` | Exception class name |

The class name is `type(exc).__name__`. The message is not copied. Invalid
combinations raise `ValueError` or `TypeError` when the event is constructed.

```python
from pyforge import JsonFormatter, RetryEvent, RetryPolicy, get_logger, retry

counts = {"scheduled": 0, "succeeded": 0, "exhausted": 0}
logger = get_logger("billing")


def observe(event: RetryEvent) -> None:
    counts[event.event_type.value] += 1
    logger.info(
        "retry %s %s",
        event.event_type.value,
        event.exception_type or "-",
        extra={"operation": "charge", "attempt": event.attempt},
    )


@retry(policy=RetryPolicy(max_attempts=3), retry_on=(TimeoutError,), observer=observe)
def fetch(url: str) -> str:
    return client.get(url, timeout=2.0).text
```

`counts` is ordinary application state. `JsonFormatter` can format the log
record, and it still applies only the redaction rules in the security notes.
PyForge does not install a handler, a metrics exporter, or a tracer. The
`client` and its timeout belong to the caller.
