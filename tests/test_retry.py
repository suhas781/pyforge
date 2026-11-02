"""Deterministic tests for RetryPolicy and the retry decorator."""

import asyncio
import importlib
import logging
from dataclasses import FrozenInstanceError

import pytest

import pyforge
from pyforge import RetryPolicy, retry


def test_policy_exponential_backoff_and_cap() -> None:
    policy = RetryPolicy(max_attempts=5, initial_delay=0.5, max_delay=1.5, multiplier=2)
    assert [policy.delay_for(i) for i in range(1, 5)] == [0.5, 1.0, 1.5, 1.5]


def test_policy_jitter_is_bounded() -> None:
    policy = RetryPolicy(initial_delay=1, max_delay=5, jitter=0.2)
    assert policy.delay_for(1, random_value=0) == pytest.approx(0.8)
    assert policy.delay_for(1, random_value=1) == pytest.approx(1.2)
    assert policy.delay_for(1, random_value=0.5) == pytest.approx(1.0)


def test_policy_accepts_boundary_values() -> None:
    zero = RetryPolicy(max_attempts=1, initial_delay=0, max_delay=0, multiplier=1, jitter=0)
    assert zero.delay_for(1, random_value=0) == 0.0
    assert zero.delay_for(1, random_value=1) == 0.0

    full_jitter = RetryPolicy(initial_delay=1, max_delay=10, multiplier=1, jitter=1)
    assert full_jitter.delay_for(1, random_value=0) == 0.0
    assert full_jitter.delay_for(1, random_value=1) == 2.0

    integers = RetryPolicy(max_attempts=1, initial_delay=1, max_delay=1, multiplier=1, jitter=0)
    assert integers.delay_for(1, random_value=1) == 1.0


def test_jitter_respects_max_delay_cap() -> None:
    policy = RetryPolicy(initial_delay=4, max_delay=5, multiplier=2, jitter=1)
    assert policy.delay_for(1, random_value=1) == 5.0
    assert policy.delay_for(2, random_value=0.5) == 5.0
    assert policy.delay_for(2, random_value=0) == 0.0


def test_max_delay_can_be_below_initial_delay() -> None:
    policy = RetryPolicy(initial_delay=2, max_delay=0.5, multiplier=2, jitter=0)
    assert policy.delay_for(1, random_value=0.5) == 0.5


def test_huge_backoff_is_capped() -> None:
    overflow = RetryPolicy(initial_delay=1, max_delay=3, multiplier=10, jitter=0)
    assert overflow.delay_for(10_000, random_value=0.5) == 3.0

    infinite = RetryPolicy(initial_delay=1, max_delay=3, multiplier=1.1, jitter=0)
    assert infinite.delay_for(10_000, random_value=0.5) == 3.0

    zero = RetryPolicy(initial_delay=0, max_delay=4, multiplier=10, jitter=0)
    assert zero.delay_for(10_000, random_value=0) == 0.0


def test_policy_is_immutable() -> None:
    policy = RetryPolicy()
    with pytest.raises(FrozenInstanceError):
        policy.max_attempts = 9  # type: ignore[misc]
    assert not hasattr(policy, "__dict__")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_attempts": 0}, "max_attempts must be at least 1"),
        ({"max_attempts": -3}, "max_attempts must be at least 1"),
        ({"max_attempts": True}, "max_attempts must be an integer"),
        ({"max_attempts": 1.5}, "max_attempts must be an integer"),
        ({"initial_delay": -1}, "initial_delay cannot be negative"),
        ({"initial_delay": float("nan")}, "initial_delay must be finite"),
        ({"initial_delay": float("inf")}, "initial_delay must be finite"),
        ({"initial_delay": "0"}, "initial_delay must be a real number"),
        ({"initial_delay": True}, "initial_delay must be a real number"),
        ({"max_delay": -1}, "max_delay cannot be negative"),
        ({"max_delay": float("inf")}, "max_delay must be finite"),
        ({"multiplier": 0.5}, "multiplier must be at least 1"),
        ({"multiplier": -1}, "multiplier must be at least 1"),
        ({"multiplier": float("inf")}, "multiplier must be finite"),
        ({"multiplier": True}, "multiplier must be a real number"),
        ({"jitter": 1.1}, "jitter must be between 0 and 1"),
        ({"jitter": -0.1}, "jitter must be between 0 and 1"),
        ({"jitter": float("nan")}, "jitter must be finite"),
        ({"jitter": True}, "jitter must be a real number"),
    ],
)
def test_invalid_policy_is_rejected(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        RetryPolicy(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("failed_attempt", "random_value"),
    [
        (0, 0.5),
        (-1, 0.5),
        (True, 0.5),
        (1.5, 0.5),
        (1, -0.01),
        (1, 1.01),
        (1, float("nan")),
        (1, float("inf")),
        (1, True),
        (1, "0.5"),
    ],
)
def test_invalid_delay_inputs_are_rejected(failed_attempt: object, random_value: object) -> None:
    policy = RetryPolicy()
    with pytest.raises(ValueError):
        policy.delay_for(failed_attempt, random_value)  # type: ignore[arg-type]


def test_sync_succeeds_on_first_attempt_without_sleeping() -> None:
    calls = 0
    delays: list[float] = []
    draws = 0

    def random_value() -> float:
        nonlocal draws
        draws += 1
        return 0.5

    @retry(
        policy=RetryPolicy(max_attempts=4),
        retry_on=(TimeoutError,),
        sleep=delays.append,
        random_value=random_value,
    )
    def operation() -> int:
        nonlocal calls
        calls += 1
        return 0

    assert operation() == 0
    assert calls == 1
    assert delays == []
    assert draws == 0


def test_sync_default_sleep_is_selected_without_waiting() -> None:
    @retry(policy=RetryPolicy(max_attempts=2), retry_on=(TimeoutError,))
    def operation() -> str:
        return "ok"

    assert operation() == "ok"


def test_sync_function_retries_then_succeeds() -> None:
    attempts = 0
    delays: list[float] = []

    @retry(
        policy=RetryPolicy(max_attempts=3, initial_delay=0.1),
        retry_on=(TimeoutError,),
        sleep=delays.append,
        random_value=lambda: 0.5,
    )
    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("temporary")
        return "done"

    assert operation() == "done"
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_sync_jitter_delays_use_each_random_draw_once() -> None:
    attempts = 0
    delays: list[float] = []
    draws = iter((0.0, 1.0))

    @retry(
        policy=RetryPolicy(max_attempts=3, initial_delay=1, max_delay=10, multiplier=2, jitter=0.5),
        retry_on=(TimeoutError,),
        sleep=delays.append,
        random_value=lambda: next(draws),
    )
    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("temporary")
        return "done"

    assert operation() == "done"
    assert delays == [0.5, 3.0]


def test_zero_delay_is_passed_to_injected_sleep() -> None:
    attempts = 0
    delays: list[float] = []

    @retry(
        policy=RetryPolicy(max_attempts=2, initial_delay=0, max_delay=0),
        retry_on=(TimeoutError,),
        sleep=delays.append,
        random_value=lambda: 0.5,
    )
    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary")
        return "done"

    assert operation() == "done"
    assert delays == [0.0]


def test_sync_function_reraises_final_exception() -> None:
    attempts = 0
    error = TimeoutError("still unavailable")

    @retry(
        policy=RetryPolicy(max_attempts=2),
        retry_on=(TimeoutError,),
        sleep=lambda _: None,
    )
    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(TimeoutError, match="still unavailable") as caught:
        operation()
    assert attempts == 2
    assert caught.value is error


def test_single_attempt_does_not_sleep() -> None:
    attempts = 0
    delays: list[float] = []
    error = TimeoutError("once")

    @retry(
        policy=RetryPolicy(max_attempts=1, initial_delay=5),
        retry_on=(TimeoutError,),
        sleep=delays.append,
    )
    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(TimeoutError) as caught:
        operation()
    assert attempts == 1
    assert delays == []
    assert caught.value is error


def test_non_retryable_exception_propagates_immediately() -> None:
    attempts = 0
    delays: list[float] = []

    @retry(
        policy=RetryPolicy(max_attempts=5),
        retry_on=(TimeoutError,),
        sleep=delays.append,
    )
    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("invalid input")

    with pytest.raises(ValueError, match="invalid input"):
        operation()
    assert attempts == 1
    assert delays == []


def test_configured_exception_subclasses_are_retried() -> None:
    class Transient(Exception):
        pass

    class Child(Transient):
        pass

    attempts = 0

    @retry(
        policy=RetryPolicy(max_attempts=2, initial_delay=0),
        retry_on=(Transient,),
        sleep=lambda _: None,
        random_value=lambda: 0.5,
    )
    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise Child("child")
        return "ok"

    assert operation() == "ok"
    assert attempts == 2


def test_any_configured_exception_type_is_retried() -> None:
    attempts = 0

    @retry(
        policy=RetryPolicy(max_attempts=3, initial_delay=0),
        retry_on=(TimeoutError, ConnectionError),
        sleep=lambda _: None,
        random_value=lambda: 0.5,
    )
    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("timed out")
        if attempts == 2:
            raise ConnectionError("reset")
        return "ok"

    assert operation() == "ok"
    assert attempts == 3


def test_default_policy_stops_after_three_attempts() -> None:
    attempts = 0

    @retry(retry_on=(TimeoutError,), sleep=lambda _: None, random_value=lambda: 0.5)
    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("nope")

    with pytest.raises(TimeoutError, match="nope"):
        operation()
    assert attempts == RetryPolicy().max_attempts == 3


def test_default_retry_on_retries_exception_subclasses() -> None:
    attempts = 0

    @retry(
        policy=RetryPolicy(max_attempts=2, initial_delay=0),
        sleep=lambda _: None,
        random_value=lambda: 0.5,
    )
    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary")
        return "ok"

    assert operation() == "ok"
    assert attempts == 2


def test_sync_retries_forward_the_same_arguments() -> None:
    seen: list[tuple[int, str]] = []

    @retry(
        policy=RetryPolicy(max_attempts=3, initial_delay=0),
        retry_on=(TimeoutError,),
        sleep=lambda _: None,
        random_value=lambda: 0.5,
    )
    def operation(left: int, *, label: str) -> str:
        seen.append((left, label))
        if len(seen) < 2:
            raise TimeoutError("temporary")
        return label

    assert operation(7, label="ok") == "ok"
    assert seen == [(7, "ok"), (7, "ok")]


def test_wrappers_do_not_share_attempt_state() -> None:
    first_calls = 0
    second_calls = 0

    @retry(
        policy=RetryPolicy(max_attempts=3, initial_delay=0),
        retry_on=(TimeoutError,),
        sleep=lambda _: None,
        random_value=lambda: 0.5,
    )
    def first() -> str:
        nonlocal first_calls
        first_calls += 1
        if first_calls < 2:
            raise TimeoutError("temporary")
        return "a"

    @retry(
        policy=RetryPolicy(max_attempts=3, initial_delay=0),
        retry_on=(TimeoutError,),
        sleep=lambda _: None,
        random_value=lambda: 0.5,
    )
    def second() -> str:
        nonlocal second_calls
        second_calls += 1
        return "b"

    assert first() == "a"
    assert second() == "b"
    assert first_calls == 2
    assert second_calls == 1


def test_sync_wrapper_preserves_metadata() -> None:
    @retry(retry_on=(TimeoutError,), sleep=lambda _: None)
    def operation(value: int) -> int:
        """Return the value."""
        return value

    assert operation.__name__ == "operation"
    assert operation.__doc__ == "Return the value."
    assert operation.__module__ == __name__
    assert operation.__qualname__ == operation.__wrapped__.__qualname__
    assert operation.__annotations__ == {"value": int, "return": int}
    assert operation(4) == 4


class Halt(BaseException):
    """Custom non-Exception used to prove the decorator does not catch it."""


@pytest.mark.parametrize(
    "exc_type",
    [KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError, Halt],
)
def test_base_exceptions_are_not_retried(exc_type: type[BaseException]) -> None:
    attempts = 0
    delays: list[float] = []

    @retry(
        policy=RetryPolicy(max_attempts=4),
        retry_on=(Exception,),
        sleep=delays.append,
        random_value=lambda: 0.5,
    )
    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise exc_type()

    with pytest.raises(exc_type):
        operation()
    assert attempts == 1
    assert delays == []


def test_invalid_random_value_fails_before_sleep_and_keeps_context() -> None:
    delays: list[float] = []

    @retry(
        policy=RetryPolicy(max_attempts=3),
        retry_on=(TimeoutError,),
        sleep=delays.append,
        random_value=lambda: 2.0,
    )
    def operation() -> None:
        raise TimeoutError("temporary")

    with pytest.raises(ValueError, match="random_value") as caught:
        operation()
    assert delays == []
    assert isinstance(caught.value.__context__, TimeoutError)


def test_empty_retry_exception_tuple_is_rejected() -> None:
    with pytest.raises(ValueError, match="retry_on"):
        retry(retry_on=())


@pytest.mark.parametrize(
    ("retry_on", "exc_type"),
    [
        ((BaseException,), TypeError),
        ((KeyboardInterrupt,), TypeError),
        ((asyncio.CancelledError,), TypeError),
        ((ValueError, str), TypeError),
        ((ValueError(),), TypeError),
        ("TimeoutError", TypeError),
        (ValueError, TypeError),
        ([ValueError], TypeError),
    ],
)
def test_invalid_retry_on_is_rejected(retry_on: object, exc_type: type[Exception]) -> None:
    with pytest.raises(exc_type, match="retry_on"):
        retry(retry_on=retry_on)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_async_succeeds_on_first_attempt_without_sleeping() -> None:
    calls = 0
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    @retry(
        policy=RetryPolicy(max_attempts=4),
        retry_on=(TimeoutError,),
        sleep=fake_sleep,
        random_value=lambda: 0.5,
    )
    async def operation() -> None:
        nonlocal calls
        calls += 1
        return None

    assert await operation() is None
    assert calls == 1
    assert delays == []


@pytest.mark.asyncio
async def test_async_default_sleep_is_selected_without_waiting() -> None:
    @retry(policy=RetryPolicy(max_attempts=2), retry_on=(TimeoutError,))
    async def operation() -> str:
        return "ok"

    assert await operation() == "ok"


@pytest.mark.asyncio
async def test_async_function_retries_then_succeeds() -> None:
    attempts = 0
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    @retry(
        policy=RetryPolicy(max_attempts=3, initial_delay=0.2),
        retry_on=(TimeoutError,),
        sleep=fake_sleep,
        random_value=lambda: 0.5,
    )
    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise TimeoutError("temporary")
        return "async done"

    assert await operation() == "async done"
    assert attempts == 2
    assert delays == [0.2]


@pytest.mark.asyncio
async def test_async_non_retryable_exception_propagates() -> None:
    attempts = 0
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    @retry(
        policy=RetryPolicy(max_attempts=4),
        retry_on=(TimeoutError,),
        sleep=fake_sleep,
    )
    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        await operation()
    assert attempts == 1
    assert delays == []


@pytest.mark.asyncio
async def test_async_reraises_final_exception() -> None:
    attempts = 0
    delays: list[float] = []
    error = TimeoutError("still")

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    @retry(
        policy=RetryPolicy(max_attempts=2, initial_delay=0.5),
        retry_on=(TimeoutError,),
        sleep=fake_sleep,
        random_value=lambda: 0.5,
    )
    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(TimeoutError, match="still") as caught:
        await operation()
    assert attempts == 2
    assert delays == [0.5]
    assert caught.value is error


@pytest.mark.asyncio
async def test_async_retries_forward_the_same_arguments() -> None:
    seen: list[str] = []

    async def fake_sleep(_delay: float) -> None:
        return None

    @retry(
        policy=RetryPolicy(max_attempts=3, initial_delay=0),
        retry_on=(TimeoutError,),
        sleep=fake_sleep,
        random_value=lambda: 0.5,
    )
    async def operation(label: str) -> str:
        seen.append(label)
        if len(seen) < 2:
            raise TimeoutError("temporary")
        return label

    assert await operation("ok") == "ok"
    assert seen == ["ok", "ok"]


@pytest.mark.asyncio
async def test_async_wrapper_preserves_metadata() -> None:
    @retry(retry_on=(TimeoutError,))
    async def operation(value: int) -> int:
        """Async fetch."""
        return value

    assert operation.__name__ == "operation"
    assert operation.__doc__ == "Async fetch."
    assert operation.__module__ == __name__
    assert operation.__qualname__ == operation.__wrapped__.__qualname__
    assert operation.__annotations__ == {"value": int, "return": int}
    assert await operation(5) == 5


@pytest.mark.asyncio
async def test_cancelled_error_from_operation_is_not_retried() -> None:
    attempts = 0
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    @retry(
        policy=RetryPolicy(max_attempts=3),
        retry_on=(Exception,),
        sleep=fake_sleep,
        random_value=lambda: 0.5,
    )
    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await operation()
    assert attempts == 1
    assert delays == []


@pytest.mark.asyncio
async def test_task_cancellation_during_operation_is_not_retried() -> None:
    attempts = 0
    delays: list[float] = []
    started = asyncio.Event()

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    @retry(
        policy=RetryPolicy(max_attempts=4, initial_delay=1),
        retry_on=(TimeoutError, AssertionError),
        sleep=fake_sleep,
        random_value=lambda: 0.5,
    )
    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            raise AssertionError("cancelled operation was retried")
        started.set()
        await asyncio.Future()

    task = asyncio.create_task(operation())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert attempts == 1
    assert delays == []
    assert task.cancelled()


@pytest.mark.asyncio
async def test_task_cancellation_during_sleep_is_not_retried() -> None:
    attempts = 0
    started = asyncio.Event()

    async def fake_sleep(_delay: float) -> None:
        started.set()
        await asyncio.Future()

    @retry(
        policy=RetryPolicy(max_attempts=4, initial_delay=1),
        retry_on=(TimeoutError,),
        sleep=fake_sleep,
        random_value=lambda: 0.5,
    )
    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            raise AssertionError("cancelled sleep was retried")
        raise TimeoutError("temporary")

    task = asyncio.create_task(operation())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert attempts == 1
    assert task.cancelled()


def test_public_api_and_version_are_explicit() -> None:
    assert pyforge.__all__ == [
        "CONTEXT_FIELD_NAMES",
        "REDACTED",
        "SENSITIVE_FIELD_NAMES",
        "SENSITIVE_FIELD_SUFFIXES",
        "JsonFormatter",
        "LogContext",
        "RetryPolicy",
        "get_logger",
        "retry",
    ]
    assert pyforge.__version__ == "0.1.0"
    assert pyforge.RetryPolicy is RetryPolicy
    assert pyforge.retry is retry


def test_import_does_not_change_root_logging() -> None:
    root = logging.getLogger()
    before = (root.level, list(root.handlers), root.disabled)
    importlib.reload(pyforge)
    after = (root.level, list(root.handlers), root.disabled)
    assert before == after
