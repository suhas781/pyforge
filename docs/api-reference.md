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
