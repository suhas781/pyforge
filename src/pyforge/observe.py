"""Optional retry lifecycle events.

An observer is a synchronous callback. It is not a logging or metrics
backend. The retry engine does not configure logging, store observers, or
make network calls.

Observer failures are isolated. An ``Exception`` raised by the callback is
discarded so it cannot change the attempt count, the delay, the returned
value, or the exception the caller sees. ``BaseException`` values, including
cancellation and keyboard interrupt, propagate.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class RetryEventType(StrEnum):
    """Lifecycle point represented by a ``RetryEvent``.

    ``SCHEDULED`` means another attempt will run after ``delay`` seconds.
    ``SUCCEEDED`` means a later attempt returned. The first attempt does not
    emit it. ``EXHAUSTED`` means the final allowed attempt failed.
    """

    SCHEDULED = "scheduled"
    SUCCEEDED = "succeeded"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class RetryEvent:
    """Immutable description of one retry lifecycle point.

    ``exception_type`` is the exception class name, never the message.
    ``delay`` is set only for ``SCHEDULED`` and is the value the engine is
    about to pass to sleep.
    """

    event_type: RetryEventType
    attempt: int
    max_attempts: int
    delay: float | None = None
    exception_type: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, RetryEventType):
            raise TypeError("event_type must be a RetryEventType")
        _attempt("attempt", self.attempt)
        _attempt("max_attempts", self.max_attempts)
        if self.attempt > self.max_attempts:
            raise ValueError("attempt cannot exceed max_attempts")
        if self.event_type is RetryEventType.SCHEDULED:
            if self.attempt >= self.max_attempts:
                raise ValueError("a scheduled event must leave an attempt remaining")
            _delay(self.delay)
            _exception_type(self.exception_type)
            return
        if self.event_type is RetryEventType.SUCCEEDED:
            if self.attempt < 2:
                raise ValueError("a succeeded event requires a previous attempt")
            if self.delay is not None or self.exception_type is not None:
                raise ValueError("a succeeded event has no delay or exception type")
            return
        if self.attempt != self.max_attempts:
            raise ValueError("an exhausted event uses the final attempt")
        if self.delay is not None:
            raise ValueError("an exhausted event has no delay")
        _exception_type(self.exception_type)


RetryObserver = Callable[[RetryEvent], object]


def notify_retry(observer: RetryObserver | None, event: RetryEvent) -> None:
    """Deliver one event, ignoring ordinary observer failures."""
    if observer is None:
        return
    try:
        observer(event)
    except Exception:
        return


def _attempt(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be an integer of at least 1")
    return value


def _delay(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("delay must be a finite number of seconds")
    delay = float(value)
    if not math.isfinite(delay) or delay < 0:
        raise ValueError("delay must be a finite number of seconds")
    return delay


def _exception_type(value: object) -> str:
    if not isinstance(value, str) or value == "" or any(character.isspace() for character in value):
        raise ValueError("exception_type must be an exception class name")
    return value
