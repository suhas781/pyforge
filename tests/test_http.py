"""Deterministic tests for HTTP retry decisions."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import sys
import traceback
from pathlib import Path

import pytest

from pyforge import RetryPolicy
from pyforge.http import (
    DEFAULT_RETRYABLE_HTTP_EXCEPTIONS,
    DEFAULT_RETRYABLE_STATUS_CODES,
    IDEMPOTENT_HTTP_METHODS,
    RetryableHTTPStatus,
    is_idempotent_method,
    is_retryable_status,
    raise_for_retryable_status,
    retry_http,
    should_retry_http,
)


class _ClientTimeout(TimeoutError):
    """Transport timeout whose message may contain a credential."""


def test_idempotent_methods_follow_the_http_spec() -> None:
    for method in ("GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE", " get "):
        assert is_idempotent_method(method) is True
    for method in ("POST", "PATCH", "CONNECT", "PROPFIND", "post"):
        assert is_idempotent_method(method) is False
    assert IDEMPOTENT_HTTP_METHODS == {"DELETE", "GET", "HEAD", "OPTIONS", "PUT", "TRACE"}


def test_method_names_are_validated() -> None:
    with pytest.raises(TypeError, match="method must be a string"):
        is_idempotent_method(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="alphabetic token"):
        is_idempotent_method("   ")
    with pytest.raises(ValueError, match="alphabetic token"):
        is_idempotent_method("GET /secret")


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_default_retryable_statuses(status: int) -> None:
    assert status in DEFAULT_RETRYABLE_STATUS_CODES
    assert is_retryable_status(status) is True
    assert should_retry_http("GET", status_code=status) is True


@pytest.mark.parametrize("status", [200, 201, 204, 301, 400, 401, 403, 404, 409, 501])
def test_ordinary_statuses_are_not_retried(status: int) -> None:
    assert is_retryable_status(status) is False
    assert should_retry_http("GET", status_code=status) is False
    raise_for_retryable_status("GET", status)


def test_custom_status_set_is_copied_and_exact() -> None:
    allowed = {503}
    assert is_retryable_status(503, retryable_statuses=allowed) is True
    assert is_retryable_status(500, retryable_statuses=allowed) is False
    allowed.add(500)
    assert is_retryable_status(500, retryable_statuses=frozenset({503})) is False
    assert is_retryable_status(500, retryable_statuses=set()) is False


def test_status_configuration_rejects_invalid_values() -> None:
    with pytest.raises(TypeError, match="status code must be an integer"):
        is_retryable_status(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="from 100 to 599"):
        is_retryable_status(99)
    with pytest.raises(ValueError, match="from 100 to 599"):
        is_retryable_status(600)
    with pytest.raises(TypeError, match="collection of status codes"):
        is_retryable_status(503, retryable_statuses="503")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="status code must be an integer"):
        is_retryable_status(503, retryable_statuses=[True])  # type: ignore[list-item]


def test_unsafe_methods_require_an_explicit_opt_in() -> None:
    assert should_retry_http("POST", status_code=503) is False
    assert should_retry_http("PATCH", status_code=429) is False
    raise_for_retryable_status("POST", 503)
    assert should_retry_http("POST", status_code=503, allow_unsafe_method=True) is True
    with pytest.raises(RetryableHTTPStatus, match="status 503 for POST") as caught:
        raise_for_retryable_status("POST", 503, allow_unsafe_method=True)
    assert caught.value.method == "POST"
    assert caught.value.status_code == 503
    assert caught.value.error_type is None


def test_invalid_status_is_rejected_for_unsafe_methods_too() -> None:
    with pytest.raises(ValueError, match="from 100 to 599"):
        should_retry_http("POST", status_code=99)
    with pytest.raises(TypeError, match="must be a boolean"):
        should_retry_http("GET", status_code=503, allow_unsafe_method=1)  # type: ignore[arg-type]


def test_exception_classification_is_narrow() -> None:
    assert DEFAULT_RETRYABLE_HTTP_EXCEPTIONS == (TimeoutError, ConnectionError)
    assert should_retry_http("GET", exception=TimeoutError("slow")) is True
    assert should_retry_http("GET", exception=ConnectionRefusedError()) is True
    assert should_retry_http("GET", exception=ValueError("bug")) is False
    assert should_retry_http("POST", exception=TimeoutError("slow")) is False
    assert (
        should_retry_http("POST", exception=TimeoutError("slow"), allow_unsafe_method=True) is True
    )
    assert should_retry_http("GET", exception=asyncio.CancelledError()) is False
    with pytest.raises(TypeError, match="BaseException"):
        should_retry_http("GET", exception="timeout")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="either a status code or an exception"):
        should_retry_http("GET")
    with pytest.raises(ValueError, match="either a status code or an exception"):
        should_retry_http("GET", status_code=503, exception=TimeoutError("slow"))
    with pytest.raises(TypeError, match="tuple of Exception"):
        should_retry_http("GET", exception=TimeoutError(), retry_on=[TimeoutError])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least one"):
        should_retry_http("GET", exception=TimeoutError(), retry_on=())
    with pytest.raises(TypeError, match="Exception subclasses"):
        should_retry_http("GET", exception=TimeoutError(), retry_on=(KeyboardInterrupt,))  # type: ignore[arg-type]


def test_retryable_signal_rejects_secret_shaped_fields() -> None:
    with pytest.raises(ValueError, match="either a status code or an error type"):
        RetryableHTTPStatus("GET")
    with pytest.raises(ValueError, match="exception class name"):
        RetryableHTTPStatus("GET", error_type="token=abc123")
    with pytest.raises(ValueError, match="either a status code or an error type"):
        RetryableHTTPStatus("GET", status_code=503, error_type="TimeoutError")


def test_get_retries_server_status_with_the_existing_policy() -> None:
    policy = RetryPolicy(max_attempts=3, initial_delay=0.25, multiplier=2, jitter=0)
    delays: list[float] = []
    statuses = iter((503, 503, 200))

    @retry_http(
        method="GET",
        policy=policy,
        sleep=delays.append,
        random_value=lambda: 0.0,
    )
    def fetch() -> int:
        status = next(statuses)
        raise_for_retryable_status("GET", status)
        return status

    assert fetch() == 200
    assert delays == [policy.delay_for(1, 0.0), policy.delay_for(2, 0.0)]


def test_get_does_not_retry_a_client_error() -> None:
    calls = 0

    @retry_http(method="GET", sleep=lambda delay: (_ for _ in ()).throw(AssertionError(delay)))
    def fetch() -> int:
        nonlocal calls
        calls += 1
        raise_for_retryable_status("GET", 404)
        return 404

    assert fetch() == 404
    assert calls == 1


def test_post_status_and_timeout_stay_single_attempt_without_opt_in() -> None:
    calls = 0

    @retry_http(method="POST")
    def create() -> int:
        nonlocal calls
        calls += 1
        raise_for_retryable_status("POST", 503)
        return 503

    assert create() == 503
    assert calls == 1

    @retry_http(method="POST")
    def timeout() -> None:
        nonlocal calls
        calls += 1
        raise TimeoutError("token=abc123")

    with pytest.raises(TimeoutError, match="token=abc123"):
        timeout()
    assert calls == 2


def test_post_opt_in_retries_status_and_timeout_without_leaking_the_message() -> None:
    policy = RetryPolicy(max_attempts=2, initial_delay=0.5, jitter=0)
    delays: list[float] = []
    calls = 0

    @retry_http(
        method="POST",
        policy=policy,
        allow_unsafe_method=True,
        sleep=delays.append,
        random_value=lambda: 1.0,
    )
    def create() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _ClientTimeout("api_key=private-key")
        raise_for_retryable_status("POST", 503, allow_unsafe_method=True)
        return "ok"

    with pytest.raises(RetryableHTTPStatus, match="status 503 for POST") as caught:
        create()
    assert calls == 2
    assert delays == [policy.delay_for(1, 1.0)]
    assert caught.value.status_code == 503
    assert "private-key" not in str(caught.value)
    assert "private-key" not in repr(caught.value)


def test_exhausted_transport_error_hides_the_original_message() -> None:
    calls = 0

    @retry_http(
        method="GET",
        policy=RetryPolicy(max_attempts=2, initial_delay=0, jitter=0),
        sleep=lambda _delay: None,
        random_value=lambda: 0.5,
    )
    def fetch() -> None:
        nonlocal calls
        calls += 1
        raise _ClientTimeout("password=supersecret")

    with pytest.raises(RetryableHTTPStatus) as caught:
        fetch()
    assert calls == 2
    assert caught.value.error_type == "_ClientTimeout"
    assert caught.value.status_code is None
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    rendered = "".join(traceback.format_exception(caught.value))
    assert "password=supersecret" not in rendered
    assert "supersecret" not in rendered


def test_keyboard_interrupt_and_cancelled_error_propagate() -> None:
    @retry_http(method="GET")
    def interrupted() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        interrupted()


async def test_async_get_retries_and_cancellation_propagates() -> None:
    policy = RetryPolicy(max_attempts=2, initial_delay=0.25, jitter=0)
    delays: list[float] = []
    calls = 0

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    @retry_http(method="get", policy=policy, sleep=sleeper, random_value=lambda: 0.5)
    async def fetch() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionResetError("dropped")
        return "ok"

    assert await fetch() == "ok"
    assert delays == [policy.delay_for(1, 0.5)]
    assert fetch.__name__ == "fetch"

    @retry_http(method="GET", sleep=sleeper)
    async def cancelled() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await cancelled()
    assert delays == [policy.delay_for(1, 0.5)]

    @retry_http(method="POST", sleep=sleeper)
    async def create() -> None:
        raise TimeoutError("once")

    with pytest.raises(TimeoutError, match="once"):
        await create()


def test_custom_retry_on_and_invalid_random_value_use_the_retry_engine() -> None:
    calls = 0

    @retry_http(
        method="PUT",
        retry_on=(RuntimeError,),
        policy=RetryPolicy(max_attempts=2, jitter=0),
        sleep=lambda _delay: None,
        random_value=lambda: 2.0,
    )
    def update() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("temporary")

    with pytest.raises(ValueError, match="random_value"):
        update()
    assert calls == 1


def test_decisions_do_not_touch_sockets_environment_or_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_closed(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network call")

    monkeypatch.setattr(socket, "socket", fail_closed)
    monkeypatch.setattr(socket, "create_connection", fail_closed)
    before_env = dict(os.environ)
    root = logging.getLogger()
    before_logging = (root.level, list(root.handlers), root.disabled)
    assert should_retry_http("HEAD", status_code=504) is True
    assert should_retry_http("DELETE", exception=ConnectionError()) is True
    assert dict(os.environ) == before_env
    assert (root.level, list(root.handlers), root.disabled) == before_logging


def test_import_does_not_change_environment_or_logging(tmp_path: Path) -> None:
    script = tmp_path / "check_http_import.py"
    script.write_text(
        "\n".join(
            (
                "import logging",
                "import os",
                "import socket",
                "import sys",
                "before = dict(os.environ)",
                "root = logging.getLogger()",
                "snapshot = (root.level, list(root.handlers), root.disabled)",
                "import ssl",
                "def _blocked(*_args, **_kwargs):",
                "    raise AssertionError('socket')",
                "socket.socket = _blocked",
                "socket.create_connection = _blocked",
                "import pyforge.http",
                "assert socket.socket is _blocked",
                "assert dict(os.environ) == before",
                "assert (root.level, list(root.handlers), root.disabled) == snapshot",
                "assert 'urllib.request' not in sys.modules",
                "assert pyforge.http.should_retry_http('GET', status_code=503) is True",
                "assert pyforge.http.should_retry_http('POST', status_code=503) is False",
            )
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_sync_wrapper_preserves_the_function_name() -> None:
    @retry_http(method="OPTIONS")
    def ping() -> str:
        return "pong"

    assert ping() == "pong"
    assert ping.__name__ == "ping"


def test_retry_http_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="alphabetic token"):
        retry_http(method="GET/POST")
    with pytest.raises(TypeError, match="must be a boolean"):

        @retry_http(method="GET", allow_unsafe_method="yes")  # type: ignore[arg-type]
        def fetch() -> None:
            return None
