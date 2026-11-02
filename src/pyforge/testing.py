"""Deterministic helpers for tests of PyForge-based code.

Import them from ``pyforge.testing``. Importing ``pyforge`` does not load this
module. The helpers do not patch the standard library, do not sleep, and do
not replace ``retry`` or ``MemoryCache``.

``temporary_env`` changes the process environment for the names it is given.
That change is visible to every thread in the process. The other helpers keep
their state on the instance.
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Coroutine, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, TypeVar

from pyforge.cache import MemoryCache

T = TypeVar("T")


class FakeClock:
    """A monotonic clock that moves only when ``advance`` is called.

    The clock starts at ``start`` and stays there until a test moves it.
    ``start`` may be negative. It must be a finite real number. ``True`` and
    ``False`` are rejected. The default is ``0.0``.

    ``advance`` adds a finite duration of at least ``0``. It returns the new
    reading. Readings do not follow ``time.monotonic`` or the wall clock.
    Concurrent reads and advances are serialized by this clock's lock.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._now = _real("start", start, minimum=None)
        self._lock = threading.Lock()

    def __call__(self) -> float:
        """Return the current reading."""
        with self._lock:
            return self._now

    @property
    def now(self) -> float:
        """Return the current reading."""
        return self()

    def advance(self, seconds: float) -> float:
        """Move forward by ``seconds`` and return the new reading."""
        step = _real("seconds", seconds, minimum=0.0)
        with self._lock:
            self._now += step
            return self._now


class RecordingSleeper:
    """Record delays and return immediately.

    The instance is a ``sleep`` callable for a synchronous ``retry`` wrapper.
    ``delays`` is a snapshot. Later calls do not change a snapshot the caller
    already holds. Zero and positive delays are recorded. Invalid delays are
    not. Concurrent calls are serialized.
    """

    def __init__(self) -> None:
        self._delays: list[float] = []
        self._lock = threading.Lock()

    def __call__(self, delay: float) -> None:
        """Record ``delay`` without sleeping."""
        value = _real("delay", delay, minimum=0.0)
        with self._lock:
            self._delays.append(value)

    @property
    def delays(self) -> tuple[float, ...]:
        """Return the delays recorded so far, in call order."""
        with self._lock:
            return tuple(self._delays)


class AsyncRecordingSleeper:
    """Record delays and return an awaitable that finishes immediately.

    Pass an instance as ``sleep`` to an asynchronous ``retry`` wrapper. The
    delay is recorded when the instance is called, before the awaitable runs.
    The awaitable does not wait. Concurrent calls are serialized.
    """

    def __init__(self) -> None:
        self._sleeper = RecordingSleeper()

    def __call__(self, delay: float) -> Coroutine[object, object, None]:
        """Record ``delay`` and return a completed coroutine."""
        self._sleeper(delay)
        return _completed()

    @property
    def delays(self) -> tuple[float, ...]:
        """Return the delays recorded so far, in call order."""
        return self._sleeper.delays


class CallCount:
    """A counter for attempts inside a test double.

    ``increment`` returns the new count, starting at 1. The counter is safe
    for concurrent increments. It has no process-wide registry.
    """

    def __init__(self) -> None:
        self._count = 0
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        """Return how many times ``increment`` has been called."""
        with self._lock:
            return self._count

    def increment(self) -> int:
        """Add one and return the new count."""
        with self._lock:
            self._count += 1
            return self._count


class FailThenReturn(Generic[T]):
    """Raise a fixed number of times, then return a prepared result.

    ``failures`` is how many calls raise before the result is returned.
    ``0`` returns on the first call. ``exc_type`` must be an ``Exception``
    subclass that can be constructed with no arguments. The raised exception
    therefore has no message. ``count`` includes both failures and the later
    successful calls. Concurrent calls are serialized.
    """

    def __init__(
        self,
        failures: int,
        result: T,
        exc_type: type[Exception] = TimeoutError,
    ) -> None:
        self._failures = _count("failures", failures)
        self._result = result
        self._exc_type = _exception_type(exc_type)
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        """Return how many times this callable has been invoked."""
        with self._lock:
            return self._calls

    def __call__(self) -> T:
        """Raise while failures remain, then return the result."""
        with self._lock:
            self._calls += 1
            failed = self._calls <= self._failures
            exc_type = self._exc_type
            result = self._result
        if failed:
            raise exc_type()
        return result


@dataclass(frozen=True, slots=True)
class ClockedCache:
    """A ``MemoryCache`` bound to a ``FakeClock``.

    Advancing ``clock`` is the supported way to expire entries. The cache's
    private attributes stay private.
    """

    cache: MemoryCache
    clock: FakeClock

    @classmethod
    def create(cls, max_entries: int, *, start: float = 0.0) -> ClockedCache:
        """Build a cache that reads ``start`` until the clock advances."""
        clock = FakeClock(start)
        return cls(cache=MemoryCache(max_entries, clock=clock), clock=clock)


@contextmanager
def temporary_env(values: Mapping[str, str | None]) -> Iterator[None]:
    """Set or remove named environment variables for one block.

    A string value is stored. ``None`` removes the name. On exit, each named
    variable is restored to the value it had before the block, or removed if
    it was absent. An empty string is a present value and is restored as an
    empty string. Names that the block creates, and that were not in
    ``values``, are left in place.

    The process environment is global. Another thread can read or write the
    same names while the block runs. This helper does not lock ``os.environ``.
    Validation finishes before the first change. Exit restores the names even
    when the block raises. Error text does not include names or values.
    """
    updates = _env_updates(values)
    saved = [(name, os.environ.get(name)) for name, _value in updates]
    try:
        for name, value in updates:
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, previous in reversed(saved):
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


async def _completed() -> None:
    return None


def _real(name: str, value: object, *, minimum: float | None) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a real number")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{name} must be a finite number") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return number


def _count(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be at least 0")
    return value


def _exception_type(value: object) -> type[Exception]:
    if not isinstance(value, type) or not issubclass(value, Exception):
        raise TypeError("exc_type must be an Exception subclass")
    return value


def _env_updates(values: object) -> list[tuple[str, str | None]]:
    if not isinstance(values, Mapping):
        raise TypeError("values must be a mapping of names to strings or None")
    updates: list[tuple[str, str | None]] = []
    for key, raw in values.items():
        if not isinstance(key, str):
            raise TypeError("environment name must be a string")
        if key == "" or "=" in key or "\0" in key:
            raise ValueError(
                "environment name must be a non-empty string without '=' or a null character"
            )
        if raw is not None and not isinstance(raw, str):
            raise TypeError("environment value must be a string or None")
        updates.append((key, raw))
    return updates


__all__ = [
    "AsyncRecordingSleeper",
    "CallCount",
    "ClockedCache",
    "FailThenReturn",
    "FakeClock",
    "RecordingSleeper",
    "temporary_env",
]
