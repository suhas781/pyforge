"""JSON logging helpers that do not configure the root logger.

Only the context fields ``request_id``, ``operation``, ``attempt``, and
``component`` are emitted. Other record attributes are ignored. Secret
redaction covers the names, suffixes, and text patterns documented on
``SENSITIVE_FIELD_NAMES`` and ``SENSITIVE_FIELD_SUFFIXES``; it is not a
general secret scanner.
"""

from __future__ import annotations

import json
import logging
import math
import re
import traceback
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

REDACTED = "[REDACTED]"
CONTEXT_FIELD_NAMES = frozenset({"request_id", "operation", "attempt", "component"})
SENSITIVE_FIELD_NAMES = frozenset(
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
SENSITIVE_FIELD_SUFFIXES = (
    "_password",
    "_passwd",
    "_token",
    "_secret",
    "_api_key",
    "_authorization",
)
_MAX_DEPTH = 20
_ASSIGNMENT = re.compile(
    r"(?i)\b(access_token|refresh_token|id_token|api_key|apikey|password|passwd|token|secret)\b"
    r"\s*[=:]\s*\S+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_AUTH_HEADER = re.compile(r"(?i)\bAuthorization\s*:\s*(?:Bearer\s+)?\S+")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    return normalized in SENSITIVE_FIELD_NAMES or normalized.endswith(SENSITIVE_FIELD_SUFFIXES)


def _redact_text(text: str) -> str:
    redacted = _AUTH_HEADER.sub("Authorization: [REDACTED]", text)
    redacted = _BEARER.sub("Bearer [REDACTED]", redacted)

    def _assignment(match: re.Match[str]) -> str:
        return f"{match.group(1)}=[REDACTED]"

    return _ASSIGNMENT.sub(_assignment, redacted)


def _key_text(key: object) -> str:
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int):
        return str(key)
    if isinstance(key, float) and math.isfinite(key):
        return str(key)
    return f"<non-string-key {type(key).__qualname__}>"


def _sanitize(value: object, *, seen: set[int] | None = None, depth: int = 0) -> object:
    if depth > _MAX_DEPTH:
        return "<max-depth>"
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return "<non-finite>"
        return value
    if isinstance(value, bytes | bytearray):
        return _redact_text(bytes(value).decode("utf-8", errors="replace"))
    active = set() if seen is None else seen
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, seen=active, depth=depth)
    if isinstance(value, list | tuple):
        return _sanitize_sequence(value, seen=active, depth=depth)
    if isinstance(value, set | frozenset):
        return _sanitize_set(value, seen=active, depth=depth)
    return f"<unserializable {type(value).__qualname__}>"


def _sanitize_mapping(value: Mapping[object, object], *, seen: set[int], depth: int) -> object:
    marker = id(value)
    if marker in seen:
        return "<circular>"
    seen.add(marker)
    try:
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            key_text = _key_text(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = REDACTED
            else:
                sanitized[key_text] = _sanitize(item, seen=seen, depth=depth + 1)
        return sanitized
    finally:
        seen.discard(marker)


def _sanitize_sequence(
    value: list[object] | tuple[object, ...], *, seen: set[int], depth: int
) -> object:
    marker = id(value)
    if marker in seen:
        return "<circular>"
    seen.add(marker)
    try:
        return [_sanitize(item, seen=seen, depth=depth + 1) for item in value]
    finally:
        seen.discard(marker)


def _sanitize_set(
    value: set[object] | frozenset[object], *, seen: set[int], depth: int
) -> list[object]:
    # Sets cannot contain themselves, so there is no circular-set case to record.
    return sorted(
        (_sanitize(item, seen=seen, depth=depth + 1) for item in value),
        key=_sort_key,
    )


def _sort_key(item: object) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _message_value(record: logging.LogRecord) -> object:
    if isinstance(record.msg, Mapping) and not record.args:
        return _sanitize(record.msg)
    return _sanitize(record.getMessage())


def _exception_payload(record: logging.LogRecord) -> dict[str, object] | None:
    info = record.exc_info
    if info is None or info[0] is None:
        return None
    exc_type, exc_value, exc_traceback = info
    payload: dict[str, object] = {
        "type": exc_type.__name__,
        "message": _redact_text("" if exc_value is None else str(exc_value)),
    }
    if exc_traceback is not None and exc_value is not None:
        formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        payload["traceback"] = _redact_text(formatted)
    return payload


def _timestamp(created: float) -> str:
    moment = datetime.fromtimestamp(created, UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    """Format one log record as a single JSON object.

    Always includes ``timestamp`` (UTC, milliseconds, ``Z`` suffix), ``level``,
    ``logger``, and ``message``. Adds ``request_id``, ``operation``,
    ``component``, and ``attempt`` only when those record attributes are
    present and usable. ``attempt`` is included only for a non-boolean integer
    greater than or equal to zero. All other record attributes are omitted.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": _timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": _message_value(record),
        }
        for field in ("request_id", "operation", "component"):
            if hasattr(record, field):
                value = getattr(record, field)
                if value is not None:
                    payload[field] = _sanitize(value)
        attempt = getattr(record, "attempt", None)
        if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt >= 0:
            payload["attempt"] = attempt
        exception = _exception_payload(record)
        if exception is not None:
            payload["exception"] = exception
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class LogContext:
    """Context accepted by :func:`get_logger`.

    Unknown keyword arguments raise ``TypeError``. Known fields with the wrong
    type, and negative ``attempt`` values, raise ``ValueError``.
    """

    request_id: str | None = None
    operation: str | None = None
    attempt: int | None = None
    component: str | None = None

    def __post_init__(self) -> None:
        for name in ("request_id", "operation", "component"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string or None")
        if self.attempt is None:
            return
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise ValueError("attempt must be an integer or None")
        if self.attempt < 0:
            raise ValueError("attempt must be greater than or equal to 0")

    def to_dict(self) -> dict[str, str | int]:
        """Return the context fields that were set."""
        values: dict[str, str | int] = {}
        if self.request_id is not None:
            values["request_id"] = self.request_id
        if self.operation is not None:
            values["operation"] = self.operation
        if self.attempt is not None:
            values["attempt"] = self.attempt
        if self.component is not None:
            values["component"] = self.component
        return values


class _ContextAdapter(logging.LoggerAdapter[logging.Logger]):
    def process(
        self,
        msg: Any,
        kwargs: MutableMapping[str, Any],
    ) -> tuple[Any, MutableMapping[str, Any]]:
        call_extra = kwargs.get("extra")
        merged: dict[str, Any] = {} if self.extra is None else dict(self.extra)
        if call_extra is None:
            kwargs["extra"] = merged
            return msg, kwargs
        if not isinstance(call_extra, dict):
            raise TypeError("extra must be a dict or None")
        merged.update(call_extra)
        kwargs["extra"] = merged
        return msg, kwargs


def get_logger(
    name: str,
    *,
    context: LogContext | None = None,
) -> logging.LoggerAdapter[logging.Logger]:
    """Return an adapter for ``name`` without attaching handlers.

    ``name`` must be a non-empty string other than ``"root"``. This function
    does not change the root logger, add handlers, or change propagation.
    Call-site ``extra`` overrides context fields for that call. Extra keys
    other than the four context fields are left on the record and ignored by
    :class:`JsonFormatter`.
    """
    if not isinstance(name, str) or not name or name == "root":
        raise ValueError("logger name must be a non-empty string other than 'root'")
    if context is not None and not isinstance(context, LogContext):
        raise TypeError("context must be a LogContext or None")
    bound = context.to_dict() if context is not None else {}
    return _ContextAdapter(logging.getLogger(name), bound)
