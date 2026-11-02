"""Bounded retry decorators for synchronous and asynchronous callables.

Retrying an operation can repeat its side effects. Retry only work that is
idempotent, or protect remote writes with an idempotency key.
"""

from __future__ import annotations

import asyncio
import functools
import math
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pyforge.observe import RetryEvent, RetryEventType, RetryObserver, notify_retry

F = TypeVar("F", bound=Callable[..., Any])
Random = Callable[[], float]


def _require_real(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a real number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _require_attempt_count(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("max_attempts must be an integer")
    if value < 1:
        raise ValueError("max_attempts must be at least 1")


def _require_failed_attempt(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("failed_attempt must be at least 1")
    return value


def _require_unit_interval(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("random_value must be between 0 and 1")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("random_value must be between 0 and 1")
    return float(value)


def _validate_retry_on(retry_on: object) -> None:
    if not isinstance(retry_on, tuple):
        raise TypeError("retry_on must be a tuple of Exception subclasses")
    if not retry_on:
        raise ValueError("retry_on must contain at least one exception type")
    for item in retry_on:
        if not isinstance(item, type) or not issubclass(item, Exception):
            raise TypeError("retry_on must contain Exception subclasses")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Immutable bounded exponential-backoff configuration.

    ``max_attempts`` includes the first call. Delays are in seconds.
    ``jitter`` is a fraction in ``[0, 1]``; ``0`` disables jitter. Invalid
    values raise ``ValueError`` when the policy is created.

    Example:
        policy = RetryPolicy(max_attempts=4, initial_delay=0.25, max_delay=2.0)
        policy.delay_for(failed_attempt=1, random_value=0.5)
    """

    max_attempts: int = 3
    initial_delay: float = 0.25
    max_delay: float = 5.0
    multiplier: float = 2.0
    jitter: float = 0.0

    def __post_init__(self) -> None:
        _require_attempt_count(self.max_attempts)
        initial_delay = _require_real("initial_delay", self.initial_delay)
        max_delay = _require_real("max_delay", self.max_delay)
        multiplier = _require_real("multiplier", self.multiplier)
        jitter = _require_real("jitter", self.jitter)
        if initial_delay < 0:
            raise ValueError("initial_delay cannot be negative")
        if max_delay < 0:
            raise ValueError("max_delay cannot be negative")
        if multiplier < 1:
            raise ValueError("multiplier must be at least 1")
        if not 0 <= jitter <= 1:
            raise ValueError("jitter must be between 0 and 1")

    def delay_for(self, failed_attempt: int, random_value: float = 0.5) -> float:
        """Return the delay in seconds after a 1-based failed attempt.

        ``base`` is ``initial_delay * multiplier ** (failed_attempt - 1)``,
        capped at ``max_delay``. The returned delay is
        ``base * (1 + jitter * (2 * random_value - 1))``, floored at ``0``
        and capped again at ``max_delay``. ``random_value`` must be in
        ``[0, 1]``. Very large exponents are capped instead of overflowing.

        Raises:
            ValueError: ``failed_attempt`` or ``random_value`` is invalid.
        """
        attempt = _require_failed_attempt(failed_attempt)
        draw = _require_unit_interval(random_value)
        if attempt == 1 or self.initial_delay == 0:
            scaled = float(self.initial_delay)
        else:
            try:
                scaled = float(self.initial_delay) * (float(self.multiplier) ** (attempt - 1))
            except OverflowError:
                scaled = math.inf
            if not math.isfinite(scaled):
                scaled = math.inf
        base = min(scaled, float(self.max_delay))
        factor = 1.0 + (float(self.jitter) * ((2.0 * draw) - 1.0))
        return max(0.0, min(base * factor, float(self.max_delay)))


def retry(
    *,
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    sleep: Callable[[float], Any] | None = None,
    random_value: Random = random.random,
    observer: RetryObserver | None = None,
) -> Callable[[F], F]:
    """Decorate a synchronous or asynchronous callable with bounded retries.

    Only exceptions matching ``retry_on`` are retried, including subclasses.
    The final matching exception is re-raised unchanged. ``BaseException``
    values, including ``asyncio.CancelledError``, ``KeyboardInterrupt``, and
    ``SystemExit``, are not caught and therefore are not retried.

    The default ``retry_on`` is ``(Exception,)``. Pass a narrower tuple so
    programming errors are not retried. Retrying a remote write is safe only
    when the operation is idempotent or protected by an idempotency key.

    ``sleep`` and ``random_value`` are injectable so tests do not wait on real
    time. Synchronous functions default to ``time.sleep``. Asynchronous
    functions default to ``asyncio.sleep`` and the injected sleep must be
    awaitable. ``random_value`` is called once for each delay and must return
    a number in ``[0, 1]``.

    ``observer`` receives a ``RetryEvent`` when a retry is scheduled, when a
    later attempt succeeds, and when attempts are exhausted. A first-attempt
    success emits nothing. The observer is synchronous. An ``Exception`` from
    the observer is discarded. ``BaseException`` propagates. The event carries
    the exception class name, not the message.

    Example:
        @retry(policy=RetryPolicy(max_attempts=3), retry_on=(TimeoutError,))
        def fetch() -> str:
            return "ok"
    """
    selected_policy = policy or RetryPolicy()
    _validate_retry_on(retry_on)
    if observer is not None and not callable(observer):
        raise TypeError("observer must be callable")

    def notify_failure(attempt: int, exc: Exception) -> float | None:
        if attempt >= selected_policy.max_attempts:
            notify_retry(
                observer,
                RetryEvent(
                    RetryEventType.EXHAUSTED,
                    attempt,
                    selected_policy.max_attempts,
                    exception_type=type(exc).__name__,
                ),
            )
            return None
        delay = selected_policy.delay_for(attempt, random_value())
        notify_retry(
            observer,
            RetryEvent(
                RetryEventType.SCHEDULED,
                attempt,
                selected_policy.max_attempts,
                delay,
                type(exc).__name__,
            ),
        )
        return delay

    def notify_success(attempt: int) -> None:
        if attempt == 1:
            return
        notify_retry(
            observer,
            RetryEvent(
                RetryEventType.SUCCEEDED,
                attempt,
                selected_policy.max_attempts,
            ),
        )

    def decorator(function: F) -> F:
        if asyncio.iscoroutinefunction(function):
            async_sleep = sleep if sleep is not None else asyncio.sleep
            async_function = cast(Callable[..., Awaitable[Any]], function)

            @functools.wraps(function)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                attempt = 1
                while True:
                    try:
                        result = await async_function(*args, **kwargs)
                    except retry_on as exc:
                        delay = notify_failure(attempt, exc)
                        if delay is None:
                            raise
                        await async_sleep(delay)
                        attempt += 1
                        continue
                    notify_success(attempt)
                    return result

            return cast(F, async_wrapper)

        sync_sleep = sleep if sleep is not None else time.sleep

        @functools.wraps(function)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 1
            while True:
                try:
                    result = function(*args, **kwargs)
                except retry_on as exc:
                    delay = notify_failure(attempt, exc)
                    if delay is None:
                        raise
                    sync_sleep(delay)
                    attempt += 1
                    continue
                notify_success(attempt)
                return result

        return cast(F, sync_wrapper)

    return decorator
