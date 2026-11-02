"""Tests for the structured JSON logging helpers."""

import json
import logging
import threading
from datetime import UTC, datetime

import pytest

import pyforge
import pyforge.logging as pyforge_logging
from pyforge import (
    CONTEXT_FIELD_NAMES,
    REDACTED,
    SENSITIVE_FIELD_NAMES,
    SENSITIVE_FIELD_SUFFIXES,
    JsonFormatter,
    LogContext,
    get_logger,
)


class _SecretRepr:
    def __repr__(self) -> str:
        return "super-secret-repr"


def _record(
    msg: object = "hello",
    *,
    level: int = logging.INFO,
    args: tuple[object, ...] = (),
    name: str = "billing",
    exc_info: tuple[type[BaseException] | None, BaseException | None, object] | None = None,
    **extra: object,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="x.py",
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _payload(record: logging.LogRecord) -> dict[str, object]:
    rendered = JsonFormatter().format(record)
    assert "\n" not in rendered
    parsed = json.loads(rendered)
    assert isinstance(parsed, dict)
    return parsed


def test_sensitive_contract_is_explicit() -> None:
    assert REDACTED == "[REDACTED]"
    assert CONTEXT_FIELD_NAMES == frozenset({"request_id", "operation", "attempt", "component"})
    assert SENSITIVE_FIELD_NAMES == frozenset(
        {
            "password",
            "passwd",
            "token",
            "access_token",
            "refresh_token",
            "id_token",
            "authorization",
            "secret",
            "api_key",
            "apikey",
        }
    )
    assert SENSITIVE_FIELD_SUFFIXES == (
        "_password",
        "_passwd",
        "_token",
        "_secret",
        "_api_key",
        "_authorization",
    )


def test_required_fields_and_valid_json() -> None:
    created = datetime(2023, 11, 14, 22, 13, 20, 123000, tzinfo=UTC)
    record = _record("charged")
    record.created = created.timestamp()
    payload = _payload(record)
    assert set(payload) == {"timestamp", "level", "logger", "message"}
    assert payload["timestamp"] == "2023-11-14T22:13:20.123Z"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "billing"
    assert payload["message"] == "charged"


def test_timestamp_is_utc_for_a_known_instant() -> None:
    record = _record("now")
    record.created = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC).timestamp()
    payload = _payload(record)
    assert payload["timestamp"] == "2024-01-02T03:04:05.000Z"


@pytest.mark.parametrize(
    ("level", "name"),
    [
        (logging.DEBUG, "DEBUG"),
        (logging.INFO, "INFO"),
        (logging.WARNING, "WARNING"),
        (logging.ERROR, "ERROR"),
        (logging.CRITICAL, "CRITICAL"),
    ],
)
def test_standard_levels(level: int, name: str) -> None:
    assert _payload(_record("level", level=level))["level"] == name


def test_optional_context_fields_are_included_when_present() -> None:
    payload = _payload(
        _record(
            "work",
            request_id="req-1",
            operation="charge",
            attempt=2,
            component="api",
        )
    )
    assert payload["request_id"] == "req-1"
    assert payload["operation"] == "charge"
    assert payload["attempt"] == 2
    assert payload["component"] == "api"


@pytest.mark.parametrize("attempt", [True, -1, "2", 1.5, None])
def test_unusable_attempt_is_omitted(attempt: object) -> None:
    payload = _payload(_record("work", attempt=attempt))
    assert "attempt" not in payload


def test_zero_attempt_is_included() -> None:
    assert _payload(_record("work", attempt=0))["attempt"] == 0


def test_unknown_extra_fields_are_omitted() -> None:
    payload = _payload(_record("work", password="hunter2", request_id="req-9"))
    rendered = json.dumps(payload)
    assert "hunter2" not in rendered
    assert payload["request_id"] == "req-9"
    assert "password" not in payload


def test_mapping_message_redacts_sensitive_fields() -> None:
    payload = _payload(
        _record(
            {
                "user": "ada",
                "password": "hunter2",
                "Password": "again",
                "token": "tok-1",
                "Authorization": "Bearer header-secret",
                "api_key": "key-1",
                "API-Key": "key-2",
                "user_password": "nested-secret",
                "session_token": "session-secret-value",
                "password_policy": "must-remain",
                "sessionToken": "camel-case-remains",
                "profile": {"access_token": "access-secret", "city": "Paris"},
            }
        )
    )
    message = payload["message"]
    assert isinstance(message, dict)
    rendered = json.dumps(payload, ensure_ascii=False)
    for secret in (
        "hunter2",
        "again",
        "tok-1",
        "header-secret",
        "key-1",
        "key-2",
        "nested-secret",
        "session-secret-value",
        "access-secret",
    ):
        assert secret not in rendered
    assert message["password"] == REDACTED
    assert message["token"] == REDACTED
    assert message["Authorization"] == REDACTED
    assert message["api_key"] == REDACTED
    assert message["API-Key"] == REDACTED
    assert message["user_password"] == REDACTED
    assert message["session_token"] == REDACTED
    assert message["password_policy"] == "must-remain"
    assert message["sessionToken"] == "camel-case-remains"
    assert message["user"] == "ada"
    assert message["profile"] == {"access_token": REDACTED, "city": "Paris"}


def test_string_patterns_redact_password_token_and_authorization() -> None:
    message = _payload(
        _record("cafe password=s3cret token: abc Authorization: Bearer super-secret user=ada")
    )["message"]
    assert message == (
        "cafe password=[REDACTED] token=[REDACTED] Authorization: [REDACTED] user=ada"
    )
    assert "s3cret" not in str(message)
    assert "super-secret" not in str(message)
    standalone = _payload(_record("Bearer raw-token"))["message"]
    assert standalone == "Bearer [REDACTED]"


def test_unicode_is_preserved() -> None:
    payload = _payload(_record("café 请求", operation="收费"))
    assert payload["message"] == "café 请求"
    assert payload["operation"] == "收费"
    rendered = JsonFormatter().format(_record("café 请求", operation="收费"))
    assert "\\u" not in rendered


def test_serialization_edge_cases() -> None:
    loop: dict[str, object] = {"name": "cycle"}
    loop["self"] = loop
    items: list[object] = ["ok"]
    items.append(items)
    payload = _payload(
        _record(
            {
                "count": 7,
                "value": 1.5,
                "flag": True,
                "empty": None,
                "missing": float("nan"),
                "huge": float("inf"),
                "blob": b"token=abc",
                "raw": bytearray(b"token=zzz"),
                "tags": {"b", "a"},
                "loop": loop,
                "items": items,
                "custom": _SecretRepr(),
                _SecretRepr(): "kept",
                True: "yes",
                False: "no",
                2: "number-key",
                1.5: "float-key",
            }
        )
    )
    message = payload["message"]
    assert isinstance(message, dict)
    rendered = json.dumps(payload)
    assert "super-secret-repr" not in rendered
    assert "abc" not in rendered
    assert message["count"] == 7
    assert message["value"] == 1.5
    assert message["flag"] is True
    assert message["empty"] is None
    assert message["missing"] == "<non-finite>"
    assert message["huge"] == "<non-finite>"
    assert message["blob"] == "token=[REDACTED]"
    assert message["raw"] == "token=[REDACTED]"
    assert message["tags"] == ["a", "b"]
    assert message["loop"]["self"] == "<circular>"
    assert message["items"] == ["ok", "<circular>"]
    assert message["custom"] == "<unserializable _SecretRepr>"
    assert message["<non-string-key _SecretRepr>"] == "kept"
    assert message["true"] == "yes"
    assert message["false"] == "no"
    assert message["2"] == "number-key"
    assert message["1.5"] == "float-key"


def test_none_context_values_and_empty_context_are_omitted() -> None:
    assert LogContext().to_dict() == {}
    adapter = get_logger("pyforge.tests.noextra", context=LogContext(component="api"))
    handler = _ListHandler()
    handler.setFormatter(JsonFormatter())
    adapter.logger.setLevel(logging.INFO)
    adapter.logger.addHandler(handler)
    adapter.logger.propagate = False
    try:
        adapter.info("plain")
    finally:
        adapter.logger.handlers.clear()
    logged = json.loads(handler.lines[0])
    assert logged["component"] == "api"
    assert "request_id" not in logged
    payload = _payload(_record("work", request_id=None, operation=None, component=None))
    assert "request_id" not in payload
    assert "operation" not in payload
    assert "component" not in payload
    record = _record("failed")
    record.exc_info = (RuntimeError, RuntimeError("token=abc"), None)
    exception = _payload(record)["exception"]
    assert isinstance(exception, dict)
    assert exception["message"] == "token=[REDACTED]"
    assert "traceback" not in exception


def test_deeply_nested_payload_stops_and_hides_the_inner_secret() -> None:
    nested: dict[str, object] = {"password": "bottom-secret"}
    for _ in range(25):
        nested = {"child": nested}
    rendered = json.dumps(_payload(_record(nested)))
    assert "bottom-secret" not in rendered
    assert "<max-depth>" in rendered


def test_percent_formatting_is_redacted_after_interpolation() -> None:
    payload = _payload(_record("password=%s user=%s", args=("s3cret", "ada")))
    assert payload["message"] == "password=[REDACTED] user=ada"


def test_exception_type_message_and_traceback_are_redacted() -> None:
    try:
        raise RuntimeError("password=s3cret")
    except RuntimeError:
        record = _record("failed", level=logging.ERROR, exc_info=__import__("sys").exc_info())
    payload = _payload(record)
    exception = payload["exception"]
    assert isinstance(exception, dict)
    assert exception["type"] == "RuntimeError"
    assert exception["message"] == "password=[REDACTED]"
    traceback_text = exception["traceback"]
    assert isinstance(traceback_text, str)
    assert "RuntimeError" in traceback_text
    assert "s3cret" not in traceback_text
    assert "s3cret" not in json.dumps(payload)


def test_log_context_and_get_logger_attach_context() -> None:
    context = LogContext(request_id="req-3", operation="charge", attempt=1, component="api")
    assert context.to_dict() == {
        "request_id": "req-3",
        "operation": "charge",
        "attempt": 1,
        "component": "api",
    }
    adapter = get_logger("pyforge.tests.context", context=context)
    handler = _ListHandler()
    handler.setFormatter(JsonFormatter())
    adapter.logger.setLevel(logging.INFO)
    adapter.logger.addHandler(handler)
    adapter.logger.propagate = False
    try:
        adapter.info("done", extra={"attempt": 4, "ignored": "secret-extra"})
    finally:
        adapter.logger.handlers.clear()
    payload = json.loads(handler.lines[0])
    assert payload["request_id"] == "req-3"
    assert payload["operation"] == "charge"
    assert payload["component"] == "api"
    assert payload["attempt"] == 4
    assert "secret-extra" not in handler.lines[0]


def test_unknown_context_and_invalid_values_are_rejected() -> None:
    with pytest.raises(TypeError, match="password"):
        LogContext(password="hunter2")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="request_id"):
        LogContext(request_id=15)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="attempt"):
        LogContext(attempt=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="attempt"):
        LogContext(attempt=-1)
    with pytest.raises(ValueError, match="root"):
        get_logger("root")
    with pytest.raises(ValueError, match="root"):
        get_logger("")
    with pytest.raises(TypeError, match="LogContext"):
        get_logger("pyforge.tests.bad", context={"component": "api"})  # type: ignore[arg-type]


def test_extra_must_be_a_dict() -> None:
    adapter = get_logger("pyforge.tests.extra")
    adapter.logger.setLevel(logging.INFO)
    with pytest.raises(TypeError, match="extra"):
        adapter.info("nope", extra=["password"])  # type: ignore[arg-type]


def test_import_does_not_configure_the_root_logger() -> None:
    import importlib

    root = logging.getLogger()
    before = (root.level, list(root.handlers), root.disabled)
    importlib.reload(pyforge_logging)
    importlib.reload(pyforge)
    after = (root.level, list(root.handlers), root.disabled)
    assert before == after
    assert issubclass(JsonFormatter, logging.Formatter)
    assert pyforge_logging.logging is logging


def test_formatter_and_logger_are_safe_across_threads() -> None:
    formatter = JsonFormatter()
    records = [_record(f"message-{index}", request_id=f"req-{index}") for index in range(20)]
    formatted: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def format_one(record: logging.LogRecord) -> None:
        try:
            rendered = formatter.format(record)
            json.loads(rendered)
        except BaseException as exc:  # pragma: no cover - failure path is the assertion
            errors.append(exc)
        else:
            with lock:
                formatted.append(rendered)

    threads = [threading.Thread(target=format_one, args=(record,)) for record in records]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(formatted) == 20

    adapter = get_logger("pyforge.tests.threads")
    handler = _ListHandler()
    handler.setFormatter(JsonFormatter())
    adapter.logger.setLevel(logging.INFO)
    adapter.logger.addHandler(handler)
    adapter.logger.propagate = False
    try:
        workers = [
            threading.Thread(target=adapter.info, args=(f"thread-{index}",)) for index in range(12)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
    finally:
        adapter.logger.handlers.clear()
    assert len(handler.lines) == 12
    assert all(json.loads(line)["logger"] == "pyforge.tests.threads" for line in handler.lines)


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))
