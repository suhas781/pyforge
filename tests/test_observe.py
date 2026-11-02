"""Deterministic tests for retry lifecycle events."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from pyforge import (
    JsonFormatter,
    RetryableHTTPStatus,
    RetryEvent,
    RetryEventType,
    RetryPolicy,
    get_logger,
    raise_for_retryable_status,
    retry,
    retry_http,
)
from pyforge.observe import notify_retry


def _policy(**overrides: object) -> RetryPolicy:
    values: dict[str, object] = {
        "max_attempts": 3,
        "initial_delay": 0.25,
        "multiplier": 2,
        "jitter": 0,
    }
    values.update(overrides)
    return RetryPolicy(**values)  # type: ignore[arg-type]


def test_first_success_emits_nothing() -> None:
    events: list[RetryEvent] = []

    @retry(
        observer=events.append, sleep=lambda _delay: (_ for _ in ()).throw(AssertionError("slept"))
    )
    def fetch() -> str:
        return "ok"

    assert fetch() == "ok"
    assert events == []


def test_scheduled_then_succeeded_events_match_the_policy() -> None:
    policy = _policy()
    events: list[RetryEvent] = []
    delays: list[float] = []
    calls = 0

    @retry(
        policy=policy,
        retry_on=(TimeoutError,),
        sleep=delays.append,
        random_value=lambda: 0.0,
        observer=events.append,
    )
    def fetch() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("password=supersecret")
        return "ok"

    assert fetch() == "ok"
    assert calls == 3
    assert [event.event_type for event in events] == [
        RetryEventType.SCHEDULED,
        RetryEventType.SCHEDULED,
        RetryEventType.SUCCEEDED,
    ]
    assert delays == [policy.delay_for(1, 0.0), policy.delay_for(2, 0.0)]
    assert events[0].attempt == 1
    assert events[1].attempt == 2
    assert events[2].attempt == 3
    assert all(event.max_attempts == 3 for event in events)
    assert events[0].delay == delays[0]
    assert events[1].delay == delays[1]
    assert events[0].exception_type == "TimeoutError"
    assert events[2].delay is None
    assert events[2].exception_type is None
    rendered = " ".join(repr(event) for event in events)
    assert "supersecret" not in rendered


def test_exhausted_event_is_the_final_attempt_and_preserves_the_error() -> None:
    policy = _policy(max_attempts=2, initial_delay=0)
    events: list[RetryEvent] = []

    @retry(
        policy=policy,
        retry_on=(ConnectionError,),
        sleep=lambda _delay: None,
        random_value=lambda: 1.0,
        observer=events.append,
    )
    def fetch() -> None:
        raise ConnectionResetError("token=abc123")

    with pytest.raises(ConnectionResetError, match="token=abc123"):
        fetch()
    assert [event.event_type for event in events] == [
        RetryEventType.SCHEDULED,
        RetryEventType.EXHAUSTED,
    ]
    assert events[1].attempt == 2
    assert events[1].max_attempts == 2
    assert events[1].delay is None
    assert events[1].exception_type == "ConnectionResetError"
    assert events[0].delay == policy.delay_for(1, 1.0)
    assert "abc123" not in repr(events[1])


def test_non_retryable_exception_emits_nothing() -> None:
    events: list[RetryEvent] = []

    @retry(retry_on=(TimeoutError,), observer=events.append)
    def fetch() -> None:
        raise ValueError("bug")

    with pytest.raises(ValueError, match="bug"):
        fetch()
    assert events == []


def test_observer_exception_does_not_replace_success_or_the_application_error() -> None:
    events: list[RetryEvent] = []

    def observe(event: RetryEvent) -> None:
        events.append(event)
        raise RuntimeError("observer-broke")

    calls = 0

    @retry(
        policy=_policy(max_attempts=2, initial_delay=0.5),
        retry_on=(TimeoutError,),
        sleep=lambda _delay: None,
        random_value=lambda: 0.0,
        observer=observe,
    )
    def recover() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("password=supersecret")
        return "kept"

    assert recover() == "kept"
    assert calls == 2
    assert events[0].event_type is RetryEventType.SCHEDULED
    assert events[1].event_type is RetryEventType.SUCCEEDED

    @retry(
        policy=RetryPolicy(max_attempts=1),
        retry_on=(TimeoutError,),
        observer=observe,
    )
    def fail() -> None:
        raise TimeoutError("api_key=private-key")

    with pytest.raises(TimeoutError, match="api_key=private-key") as caught:
        fail()
    assert caught.value.__cause__ is None
    assert "observer-broke" not in str(caught.value)
    assert events[-1].event_type is RetryEventType.EXHAUSTED


def test_observer_base_exception_propagates_before_sleep() -> None:
    slept = False

    def observe(_event: RetryEvent) -> None:
        raise KeyboardInterrupt

    def sleep(_delay: float) -> None:
        nonlocal slept
        slept = True

    @retry(
        policy=RetryPolicy(max_attempts=2, initial_delay=0),
        retry_on=(TimeoutError,),
        sleep=sleep,
        random_value=lambda: 0.0,
        observer=observe,
    )
    def fetch() -> None:
        raise TimeoutError("temporary")

    with pytest.raises(KeyboardInterrupt):
        fetch()
    assert slept is False


async def test_async_events_and_cancellation() -> None:
    policy = _policy(max_attempts=3)
    events: list[RetryEvent] = []
    delays: list[float] = []
    calls = 0

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    @retry(
        policy=policy,
        retry_on=(TimeoutError,),
        sleep=sleeper,
        random_value=lambda: 0.5,
        observer=events.append,
    )
    async def fetch() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("slow")
        return "ok"

    assert await fetch() == "ok"
    assert [event.event_type for event in events] == [
        RetryEventType.SCHEDULED,
        RetryEventType.SUCCEEDED,
    ]
    assert delays == [policy.delay_for(1, 0.5)]
    assert events[1].attempt == 2

    @retry(policy=policy, retry_on=(TimeoutError,), sleep=sleeper, observer=events.append)
    async def cancelled() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await cancelled()
    assert len(events) == 2


def test_http_events_are_not_duplicated_and_omit_secrets() -> None:
    policy = _policy(max_attempts=2, initial_delay=0.25)
    events: list[RetryEvent] = []
    calls = 0

    @retry_http(
        method="GET",
        policy=policy,
        sleep=lambda _delay: None,
        random_value=lambda: 0.0,
        observer=events.append,
    )
    def fetch() -> int:
        nonlocal calls
        calls += 1
        status = 503 if calls == 1 else 200
        raise_for_retryable_status("GET", status)
        return status

    assert fetch() == 200
    assert [event.event_type for event in events] == [
        RetryEventType.SCHEDULED,
        RetryEventType.SUCCEEDED,
    ]
    assert events[0].exception_type == "RetryableHTTPStatus"
    assert events[0].delay == policy.delay_for(1, 0.0)
    assert calls == 2

    @retry_http(method="POST", observer=events.append)
    def create() -> int:
        raise_for_retryable_status("POST", 503)
        return 503

    before = len(events)
    assert create() == 503
    assert len(events) == before


def test_http_timeout_opt_in_reports_the_translated_type() -> None:
    events: list[RetryEvent] = []

    @retry_http(
        method="POST",
        allow_unsafe_method=True,
        policy=RetryPolicy(max_attempts=1),
        observer=events.append,
    )
    def create() -> None:
        raise TimeoutError("password=supersecret")

    with pytest.raises(RetryableHTTPStatus) as caught:
        create()

    assert caught.value.error_type == "TimeoutError"
    assert events[0].event_type is RetryEventType.EXHAUSTED
    assert events[0].exception_type == "RetryableHTTPStatus"
    assert "supersecret" not in repr(events[0])


def test_json_logging_adapter_does_not_receive_the_exception_message() -> None:
    handler = logging.Handler()
    lines: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(JsonFormatter().format(record))

    del handler
    capture = _Capture()
    logger = get_logger("pyforge.tests.observe")
    logger.logger.setLevel(logging.INFO)
    logger.logger.addHandler(capture)
    logger.logger.propagate = False

    def observe(event: RetryEvent) -> None:
        logger.info(
            "retry %s %s",
            event.event_type.value,
            event.exception_type or "-",
            extra={"operation": "charge", "attempt": event.attempt},
        )

    @retry(
        policy=RetryPolicy(max_attempts=1),
        retry_on=(TimeoutError,),
        observer=observe,
    )
    def fetch() -> None:
        raise TimeoutError("password=supersecret")

    try:
        with pytest.raises(TimeoutError):
            fetch()
    finally:
        logger.logger.handlers.clear()
    assert len(lines) == 1
    assert "exhausted" in lines[0]
    assert "TimeoutError" in lines[0]
    assert "supersecret" not in lines[0]


def test_event_validation_and_isolated_notification() -> None:
    with pytest.raises(TypeError, match="RetryEventType"):
        RetryEvent("scheduled", 1, 2)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="attempt must be an integer"):
        RetryEvent(RetryEventType.SCHEDULED, True, 2, 0.0, "TimeoutError")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_attempts"):
        RetryEvent(RetryEventType.SCHEDULED, 1, 0, 0.0, "TimeoutError")
    with pytest.raises(ValueError, match="cannot exceed"):
        RetryEvent(RetryEventType.EXHAUSTED, 3, 2, exception_type="TimeoutError")
    with pytest.raises(ValueError, match="leave an attempt"):
        RetryEvent(RetryEventType.SCHEDULED, 2, 2, 0.0, "TimeoutError")
    with pytest.raises(ValueError, match="delay"):
        RetryEvent(RetryEventType.SCHEDULED, 1, 2, None, "TimeoutError")
    with pytest.raises(ValueError, match="delay"):
        RetryEvent(RetryEventType.SCHEDULED, 1, 2, True, "TimeoutError")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="delay"):
        RetryEvent(RetryEventType.SCHEDULED, 1, 2, float("nan"), "TimeoutError")
    with pytest.raises(ValueError, match="delay"):
        RetryEvent(RetryEventType.SCHEDULED, 1, 2, -1, "TimeoutError")
    with pytest.raises(ValueError, match="exception class name"):
        RetryEvent(RetryEventType.SCHEDULED, 1, 2, 0, "")
    with pytest.raises(ValueError, match="exception class name"):
        RetryEvent(RetryEventType.SCHEDULED, 1, 2, 0, "Timeout Error")
    with pytest.raises(ValueError, match="exception class name"):
        RetryEvent(RetryEventType.SCHEDULED, 1, 2, 0, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="previous attempt"):
        RetryEvent(RetryEventType.SUCCEEDED, 1, 2)
    with pytest.raises(ValueError, match="no delay or exception"):
        RetryEvent(RetryEventType.SUCCEEDED, 2, 2, 0.0)
    with pytest.raises(ValueError, match="no delay or exception"):
        RetryEvent(RetryEventType.SUCCEEDED, 2, 2, exception_type="TimeoutError")
    with pytest.raises(ValueError, match="final attempt"):
        RetryEvent(RetryEventType.EXHAUSTED, 1, 2, exception_type="TimeoutError")
    with pytest.raises(ValueError, match="no delay"):
        RetryEvent(RetryEventType.EXHAUSTED, 2, 2, 0.1, "TimeoutError")
    valid = RetryEvent(RetryEventType.SCHEDULED, 1, 2, 0, "TimeoutError")
    assert notify_retry(None, valid) is None

    def fail(_event: RetryEvent) -> None:
        raise RuntimeError("observer-broke")

    assert notify_retry(fail, valid) is None
    with pytest.raises(asyncio.CancelledError):
        notify_retry(lambda _event: (_ for _ in ()).throw(asyncio.CancelledError()), valid)
    with pytest.raises(TypeError, match="callable"):
        retry(observer=1)  # type: ignore[arg-type]


def test_observers_do_not_open_sockets_or_change_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_closed(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network call")

    monkeypatch.setattr(socket, "socket", fail_closed)
    monkeypatch.setattr(socket, "create_connection", fail_closed)
    before = dict(os.environ)
    root = logging.getLogger()
    snapshot = (root.level, list(root.handlers), root.disabled)
    event = RetryEvent(RetryEventType.SUCCEEDED, 2, 2)
    notify_retry(lambda _event: None, event)
    assert dict(os.environ) == before
    assert (root.level, list(root.handlers), root.disabled) == snapshot


def test_import_does_not_configure_logging_or_the_environment(tmp_path: Path) -> None:
    script = tmp_path / "check_observe_import.py"
    script.write_text(
        "\n".join(
            (
                "import logging",
                "import os",
                "before = dict(os.environ)",
                "root = logging.getLogger()",
                "snapshot = (root.level, list(root.handlers), root.disabled)",
                "import pyforge.observe",
                "assert dict(os.environ) == before",
                "assert (root.level, list(root.handlers), root.disabled) == snapshot",
                "assert pyforge.observe.RetryEventType.EXHAUSTED.value == 'exhausted'",
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
