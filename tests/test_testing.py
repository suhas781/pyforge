"""Deterministic tests for pyforge.testing."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import pyforge
from pyforge import RetryPolicy, retry
from pyforge.testing import (
    AsyncRecordingSleeper,
    CallCount,
    ClockedCache,
    FailThenReturn,
    FakeClock,
    RecordingSleeper,
    temporary_env,
)


def test_public_testing_api_is_explicit() -> None:
    assert pyforge.testing.__all__ == [
        "AsyncRecordingSleeper",
        "CallCount",
        "ClockedCache",
        "FailThenReturn",
        "FakeClock",
        "RecordingSleeper",
        "temporary_env",
    ]
    assert "FakeClock" not in pyforge.__all__
    assert not hasattr(pyforge, "FakeClock")


def test_fake_clock_starts_still_and_advances() -> None:
    clock = FakeClock()
    assert clock() == 0.0
    assert clock.now == 0.0
    assert clock.advance(0) == 0.0
    assert clock.advance(1.5) == 1.5
    assert clock() == 1.5
    other = FakeClock(-5)
    assert other.advance(2) == -3.0
    assert clock.now == 1.5


def test_fake_clock_rejects_invalid_times() -> None:
    with pytest.raises(TypeError, match="real number"):
        FakeClock(True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="real number"):
        FakeClock("0")  # type: ignore[arg-type]
    for start in (math.nan, math.inf, 10**400):
        with pytest.raises(ValueError, match="finite"):
            FakeClock(start)
    clock = FakeClock()
    with pytest.raises(TypeError, match="real number"):
        clock.advance(False)  # type: ignore[arg-type]
    for step in (-1, math.nan, math.inf, -(10**400)):
        with pytest.raises(ValueError, match="finite|at least"):
            clock.advance(step)
    assert clock.now == 0.0


def test_fake_clock_advances_are_thread_safe() -> None:
    clock = FakeClock()

    def worker() -> None:
        for _ in range(100):
            clock.advance(0.5)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert clock.now == 200.0


def test_recording_sleeper_records_zero_and_positive_delays() -> None:
    sleeper = RecordingSleeper()
    sleeper(0)
    sleeper(1.5)
    sleeper(2)
    recorded = sleeper.delays
    sleeper(4)
    assert recorded == (0.0, 1.5, 2.0)
    assert sleeper.delays == (0.0, 1.5, 2.0, 4.0)


def test_recording_sleeper_rejects_invalid_delays_without_recording() -> None:
    sleeper = RecordingSleeper()
    with pytest.raises(TypeError, match="real number"):
        sleeper(True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="real number"):
        sleeper("1")  # type: ignore[arg-type]
    for delay in (-0.1, math.nan, math.inf, 10**400):
        with pytest.raises(ValueError, match="finite|at least"):
            sleeper(delay)
    assert sleeper.delays == ()


def test_async_recording_sleeper_finishes_without_waiting() -> None:
    async def scenario() -> None:
        sleeper = AsyncRecordingSleeper()
        await sleeper(0)
        pending = sleeper(2)
        assert sleeper.delays == (0.0, 2.0)
        await pending
        with pytest.raises(ValueError, match="at least"):
            await sleeper(-1)
        assert sleeper.delays == (0.0, 2.0)

    asyncio.run(scenario())


def test_sync_retry_records_attempts_and_delays() -> None:
    sleeper = RecordingSleeper()
    calls = FailThenReturn(2, "ok")
    wrapped = retry(
        policy=RetryPolicy(max_attempts=4, jitter=0),
        retry_on=(TimeoutError,),
        sleep=sleeper,
        random_value=lambda: 0.0,
    )(calls)
    assert wrapped() == "ok"
    assert calls.count == 3
    assert sleeper.delays == (0.25, 0.5)


def test_sync_retry_exhaustion_is_visible_from_the_call_count() -> None:
    sleeper = RecordingSleeper()
    calls = FailThenReturn(5, "ok")
    wrapped = retry(
        policy=RetryPolicy(max_attempts=3, jitter=0),
        retry_on=(TimeoutError,),
        sleep=sleeper,
        random_value=lambda: 0.0,
    )(calls)
    with pytest.raises(TimeoutError) as caught:
        wrapped()
    assert caught.value.args == ()
    assert calls.count == 3
    assert sleeper.delays == (0.25, 0.5)


async def test_async_retry_uses_the_async_sleeper() -> None:
    sleeper = AsyncRecordingSleeper()
    calls = FailThenReturn(1, None)

    @retry(
        policy=RetryPolicy(max_attempts=3, jitter=0),
        retry_on=(TimeoutError,),
        sleep=sleeper,
        random_value=lambda: 0.0,
    )
    async def fetch() -> None:
        calls()

    assert await fetch() is None
    assert calls.count == 2
    assert sleeper.delays == (0.25,)


def test_fail_then_return_validation_and_zero_failures() -> None:
    ready = FailThenReturn(0, "ready", ValueError)
    assert ready() == "ready"
    assert ready.count == 1
    with pytest.raises(TypeError, match="integer"):
        FailThenReturn(True, "no")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer"):
        FailThenReturn(1.0, "no")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least 0"):
        FailThenReturn(-1, "no")
    with pytest.raises(TypeError, match="Exception subclass"):
        FailThenReturn(1, "no", KeyboardInterrupt)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Exception subclass"):
        FailThenReturn(1, "no", TimeoutError())  # type: ignore[arg-type]


def test_call_count_and_scripted_calls_are_thread_safe() -> None:
    counter = CallCount()
    calls = FailThenReturn(10, "ok")
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(20):
                counter.increment()
                try:
                    calls()
                except TimeoutError:
                    pass
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert counter.count == 80
    assert calls.count == 80


def test_clocked_cache_expires_when_the_fake_clock_advances() -> None:
    harness = ClockedCache.create(2, start=10)
    harness.cache.set("profile", None, ttl=5)
    assert harness.cache.get("profile") is None
    assert harness.clock.advance(5) == 15
    assert "profile" not in harness.cache
    other = ClockedCache.create(1)
    other.cache.set("profile", "kept")
    assert other.cache.get("profile") == "kept"


def test_temporary_env_restores_present_absent_and_empty_values() -> None:
    present = "PYFORGE_TESTING_PRESENT"
    absent = "PYFORGE_TESTING_ABSENT"
    empty = "PYFORGE_TESTING_EMPTY"
    neighbor = "PYFORGE_TESTING_NEIGHBOR"
    os.environ.pop(absent, None)
    os.environ[present] = "old"
    os.environ[empty] = ""
    os.environ[neighbor] = "stay"
    before = dict(os.environ)
    try:
        with temporary_env({present: "new", absent: "set", empty: None}):
            assert os.environ[present] == "new"
            assert os.environ[absent] == "set"
            assert empty not in os.environ
            assert os.environ[neighbor] == "stay"
        assert os.environ[present] == "old"
        assert absent not in os.environ
        assert os.environ[empty] == ""
        assert os.environ[neighbor] == "stay"
        assert dict(os.environ) == before
    finally:
        os.environ.pop(present, None)
        os.environ.pop(absent, None)
        os.environ.pop(empty, None)
        os.environ.pop(neighbor, None)


def test_temporary_env_restores_after_an_exception() -> None:
    name = "PYFORGE_TESTING_EXCEPTION"
    os.environ.pop(name, None)
    try:
        with pytest.raises(RuntimeError, match="boom"):
            with temporary_env({name: "secret-value"}):
                assert os.environ[name] == "secret-value"
                raise RuntimeError("boom")
        assert name not in os.environ
    finally:
        os.environ.pop(name, None)


def test_temporary_env_nested_blocks_restore_each_level() -> None:
    name = "PYFORGE_TESTING_NESTED"
    os.environ[name] = "outer"
    try:
        with temporary_env({name: "middle"}):
            with temporary_env({name: None}):
                assert name not in os.environ
            assert os.environ[name] == "middle"
        assert os.environ[name] == "outer"
    finally:
        os.environ.pop(name, None)


def test_temporary_env_leaves_untracked_names_and_rejects_invalid_input() -> None:
    tracked = "PYFORGE_TESTING_TRACKED"
    extra = "PYFORGE_TESTING_EXTRA"
    os.environ.pop(tracked, None)
    os.environ.pop(extra, None)
    try:
        with temporary_env({}):
            os.environ[extra] = "left"
        assert os.environ[extra] == "left"
        with pytest.raises(TypeError, match="mapping"):
            with temporary_env(["NOPE"]):  # type: ignore[arg-type]
                raise AssertionError("entered")
        with pytest.raises(TypeError, match="string"):
            with temporary_env({1: "x"}):  # type: ignore[dict-item]
                raise AssertionError("entered")
        for key in ("", "A=B", "A\0B"):
            with pytest.raises(ValueError, match="non-empty"):
                with temporary_env({key: "x"}):
                    raise AssertionError("entered")
        with pytest.raises(TypeError, match="string or None"):
            with temporary_env({tracked: 1, extra: "nope"}):  # type: ignore[dict-item]
                raise AssertionError("entered")
        assert tracked not in os.environ
        assert os.environ[extra] == "left"
        with temporary_env({tracked: None}):
            assert tracked not in os.environ
        assert tracked not in os.environ
    finally:
        os.environ.pop(tracked, None)
        os.environ.pop(extra, None)


def test_helpers_do_not_sleep_or_change_logging_or_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("real sleep")

    monkeypatch.setattr(time, "sleep", boom)
    monkeypatch.setattr(asyncio, "sleep", boom)
    before = dict(os.environ)
    root = logging.getLogger()
    snapshot = (root.level, list(root.handlers), root.disabled)
    clock = FakeClock()
    clock.advance(10_000)
    sleeper = RecordingSleeper()
    sleeper(0)
    sleeper(3)
    asyncio.run(AsyncRecordingSleeper()(1))
    CallCount().increment()
    assert FailThenReturn(0, 1)() == 1
    harness = ClockedCache.create(1)
    harness.cache.set("k", "v")
    assert harness.cache.get("k") == "v"
    assert dict(os.environ) == before
    assert (root.level, list(root.handlers), root.disabled) == snapshot


def test_import_does_not_load_testing_or_change_process_state(tmp_path: Path) -> None:
    script = tmp_path / "check_testing_import.py"
    script.write_text(
        "\n".join(
            (
                "import logging",
                "import os",
                "import sys",
                "before = dict(os.environ)",
                "root = logging.getLogger()",
                "snapshot = (root.level, list(root.handlers), root.disabled)",
                "import pyforge",
                "assert 'pyforge.testing' not in sys.modules",
                "assert not hasattr(pyforge, 'FakeClock')",
                "import pyforge.testing",
                "clock = pyforge.testing.FakeClock()",
                "assert clock.advance(1) == 1.0",
                "assert dict(os.environ) == before",
                "assert (root.level, list(root.handlers), root.disabled) == snapshot",
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
