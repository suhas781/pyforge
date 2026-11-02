"""HTTP retry decisions that reuse the existing retry engine.

This module does not send requests, open sockets, or enforce a timeout. The
caller configures those on the HTTP transport. A client-side timeout does not
prove that the server skipped the request, and a retry can duplicate a side
effect when the method is not idempotent.

Unsafe methods such as ``POST`` and ``PATCH`` are not retried unless the
caller passes ``allow_unsafe_method=True``. That flag is an explicit claim
that the request is protected by an idempotency key or an equivalent
guarantee. PyForge does not create or send that key.
"""

from __future__ import annotations

import asyncio
import functools
import random
import re
from collections.abc import Awaitable, Callable, Collection
from typing import Any, TypeVar, cast

from pyforge.retry import RetryPolicy, retry

F = TypeVar("F", bound=Callable[..., Any])
Random = Callable[[], float]

IDEMPOTENT_HTTP_METHODS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PUT", "TRACE"})
DEFAULT_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
DEFAULT_RETRYABLE_HTTP_EXCEPTIONS = (TimeoutError, ConnectionError)
_METHOD_TOKEN = re.compile(r"[A-Za-z]+")


class RetryableHTTPStatus(Exception):
    """Signal that one HTTP outcome should be retried.

    The message contains the method and either a status code or an exception
    class name. It does not contain a response body, headers, or the original
    exception text.
    """

    def __init__(
        self,
        method: str,
        *,
        status_code: int | None = None,
        error_type: str | None = None,
    ) -> None:
        checked_method = _method_name(method)
        if (status_code is None) == (error_type is None):
            raise ValueError("Provide either a status code or an error type")
        checked_status = None if status_code is None else _status_code(status_code)
        checked_error = None if error_type is None else _error_type(error_type)
        self.method = checked_method
        self.status_code = checked_status
        self.error_type = checked_error
        if checked_status is not None:
            message = f"retryable HTTP status {checked_status} for {checked_method}"
        else:
            message = f"retryable HTTP {checked_error} for {checked_method}"
        super().__init__(message)


def is_idempotent_method(method: str) -> bool:
    """Return whether RFC 9110 treats the method as idempotent.

    ``GET``, ``HEAD``, ``OPTIONS``, ``PUT``, ``DELETE``, and ``TRACE`` are
    idempotent. ``POST``, ``PATCH``, ``CONNECT``, and unknown methods are not.
    Comparison ignores case and surrounding whitespace.
    """
    return _method_name(method) in IDEMPOTENT_HTTP_METHODS


def is_retryable_status(
    status_code: int,
    *,
    retryable_statuses: Collection[int] | None = None,
) -> bool:
    """Return whether the status is in the retryable set.

    The default set is ``408``, ``429``, ``500``, ``502``, ``503``, and
    ``504``. ``None`` selects that set. An empty collection retries no status.
    """
    return _status_code(status_code) in _status_set(retryable_statuses)


def should_retry_http(
    method: str,
    *,
    status_code: int | None = None,
    exception: BaseException | None = None,
    allow_unsafe_method: bool = False,
    retryable_statuses: Collection[int] | None = None,
    retry_on: tuple[type[Exception], ...] = DEFAULT_RETRYABLE_HTTP_EXCEPTIONS,
) -> bool:
    """Return whether this single outcome is eligible for another attempt.

    Pass a status code or an exception, not both. Non-idempotent methods
    return ``False`` unless ``allow_unsafe_method`` is true. The decision does
    not sleep, send a request, or read the process environment.
    """
    checked_method = _method_name(method)
    opted_in = _flag("allow_unsafe_method", allow_unsafe_method)
    statuses = _status_set(retryable_statuses)
    checked_retry_on = _validate_retry_on(retry_on)
    if status_code is not None and exception is not None:
        raise ValueError("Provide either a status code or an exception")
    allowed = opted_in or checked_method in IDEMPOTENT_HTTP_METHODS
    if status_code is not None:
        code = _status_code(status_code)
        return bool(allowed and code in statuses)
    if exception is None:
        raise ValueError("Provide either a status code or an exception")
    if not isinstance(exception, BaseException):
        raise TypeError("exception must be a BaseException instance")
    return allowed and isinstance(exception, checked_retry_on)


def raise_for_retryable_status(
    method: str,
    status_code: int,
    *,
    allow_unsafe_method: bool = False,
    retryable_statuses: Collection[int] | None = None,
) -> None:
    """Raise ``RetryableHTTPStatus`` when the response should be retried.

    A non-retryable status returns ``None``. The caller still decides whether
    that status is a successful result.
    """
    if should_retry_http(
        method,
        status_code=status_code,
        allow_unsafe_method=allow_unsafe_method,
        retryable_statuses=retryable_statuses,
    ):
        raise RetryableHTTPStatus(_method_name(method), status_code=_status_code(status_code))


def retry_http(
    *,
    method: str,
    policy: RetryPolicy | None = None,
    allow_unsafe_method: bool = False,
    retryable_statuses: Collection[int] | None = None,
    retry_on: tuple[type[Exception], ...] = DEFAULT_RETRYABLE_HTTP_EXCEPTIONS,
    sleep: Callable[[float], Any] | None = None,
    random_value: Random = random.random,
) -> Callable[[F], F]:
    """Retry a callable with ``RetryPolicy`` when the HTTP outcome is eligible.

    Transport exceptions in ``retry_on`` are retried only when
    ``should_retry_http`` agrees. Status retries happen when the callable
    raises ``RetryableHTTPStatus``, usually through
    ``raise_for_retryable_status``. The exhausted attempt raises that signal;
    its message does not copy the original exception text.

    ``allow_unsafe_method`` applies to transport exceptions caught by this
    decorator. Status checks use the flag passed to
    ``raise_for_retryable_status``. Both default to false.

    This decorator does not accept a timeout. Set the timeout on the HTTP
    client that performs the request. There is no exactly-once guarantee.
    """
    checked_method = _method_name(method)
    opted_in = _flag("allow_unsafe_method", allow_unsafe_method)
    statuses = _status_set(retryable_statuses)
    checked_retry_on = _validate_retry_on(retry_on)
    bounded = retry(
        policy=policy,
        retry_on=(RetryableHTTPStatus,),
        sleep=sleep,
        random_value=random_value,
    )

    def decorator(function: F) -> F:
        def signal_for(exc: Exception) -> RetryableHTTPStatus | None:
            if should_retry_http(
                checked_method,
                exception=exc,
                allow_unsafe_method=opted_in,
                retryable_statuses=statuses,
                retry_on=checked_retry_on,
            ):
                return RetryableHTTPStatus(checked_method, error_type=type(exc).__name__)
            return None

        if asyncio.iscoroutinefunction(function):
            async_function = cast(Callable[..., Awaitable[Any]], function)

            @functools.wraps(function)
            async def async_attempt(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await async_function(*args, **kwargs)
                except checked_retry_on as exc:
                    signal = signal_for(exc)
                    if signal is None:
                        raise
                    raise signal from None

            return cast(F, bounded(async_attempt))

        @functools.wraps(function)
        def attempt(*args: Any, **kwargs: Any) -> Any:
            try:
                return function(*args, **kwargs)
            except checked_retry_on as exc:
                signal = signal_for(exc)
                if signal is None:
                    raise
                raise signal from None

        return cast(F, bounded(attempt))

    return decorator


def _method_name(method: object) -> str:
    if not isinstance(method, str):
        raise TypeError("HTTP method must be a string")
    normalized = method.strip().upper()
    if _METHOD_TOKEN.fullmatch(normalized) is None:
        raise ValueError("HTTP method must be an alphabetic token")
    return normalized


def _status_code(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("HTTP status code must be an integer")
    if not 100 <= value <= 599:
        raise ValueError("HTTP status code must be from 100 to 599")
    return value


def _status_set(values: Collection[int] | None) -> frozenset[int]:
    if values is None:
        return DEFAULT_RETRYABLE_STATUS_CODES
    if isinstance(values, (str, bytes)) or not isinstance(values, Collection):
        raise TypeError("retryable_statuses must be a collection of status codes")
    return frozenset(_status_code(item) for item in values)


def _validate_retry_on(retry_on: object) -> tuple[type[Exception], ...]:
    if not isinstance(retry_on, tuple):
        raise TypeError("retry_on must be a tuple of Exception subclasses")
    if not retry_on:
        raise ValueError("retry_on must contain at least one exception type")
    checked: list[type[Exception]] = []
    for item in retry_on:
        if not isinstance(item, type) or not issubclass(item, Exception):
            raise TypeError("retry_on must contain Exception subclasses")
        checked.append(item)
    return tuple(checked)


def _flag(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def _error_type(value: object) -> str:
    if not isinstance(value, str) or not value.isidentifier():
        raise ValueError("error_type must be an exception class name")
    return value
