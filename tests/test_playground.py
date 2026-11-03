"""Output contract for the local playground. Values come from the running server."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.client import HTTPConnection
from typing import Any

import pytest

from playground.server import STATIC, Handler
from pyforge import RetryPolicy

HOST = "127.0.0.1"


@pytest.fixture(scope="module")
def playground() -> Iterator[int]:
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer((HOST, 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _exchange(
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
) -> tuple[int, bytes]:
    connection = HTTPConnection(HOST, port, timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    status = response.status
    connection.close()
    return status, payload


def _json(port: int, method: str, path: str, body: bytes | None = None) -> tuple[int, Any]:
    status, payload = _exchange(port, method, path, body)
    return status, json.loads(payload)


def _run(port: int, module: str) -> dict[str, Any]:
    status, payload = _json(port, "POST", "/api/run", json.dumps({"module": module}).encode())
    assert status == 200, payload
    assert isinstance(payload, dict)
    return payload


def test_server_binds_to_loopback_only() -> None:
    source = (STATIC.parent / "server.py").read_text(encoding="utf-8")
    assert '("127.0.0.1", 8765)' in source
    assert "0.0.0.0" not in source


def test_frontend_displays_response_fields_without_hardcoded_results() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    for field in (
        "payload.result",
        "payload.summary",
        "payload.note",
        "payload.error",
        "payload.message",
    ):
        assert field in script
    for baked_in in ("Inventory sync completed", "req-demo-1042", "INV-2048", "demo-secret-value"):
        assert baked_in not in script
        assert baked_in not in page


def test_retry_output_contract(playground: int) -> None:
    policy = RetryPolicy(max_attempts=4, initial_delay=0.2, max_delay=1.0, multiplier=2)
    delays = [policy.delay_for(1, 0.5), policy.delay_for(2, 0.5)]
    payload = _run(playground, "retry")
    result = payload["result"]
    assert payload["module"] == "retry"
    assert result["final_result"] == "Inventory sync completed"
    assert result["total_attempts"] == 3
    assert result["retry_delays"] == delays
    events = result["lifecycle_events"]
    assert events == [
        {
            "event_type": "scheduled",
            "attempt": 1,
            "max_attempts": 4,
            "delay": delays[0],
            "exception_type": "TimeoutError",
        },
        {
            "event_type": "scheduled",
            "attempt": 2,
            "max_attempts": 4,
            "delay": delays[1],
            "exception_type": "TimeoutError",
        },
        {
            "event_type": "succeeded",
            "attempt": 3,
            "max_attempts": 4,
            "delay": None,
            "exception_type": None,
        },
    ]


def test_observe_output_lists_every_captured_event(playground: int) -> None:
    payload = _run(playground, "observe")
    retry = _run(playground, "retry")
    assert payload["module"] == "observe"
    assert payload["result"] == retry["result"]["lifecycle_events"]
    assert payload["result"]
    for event in payload["result"]:
        assert set(event) == {"event_type", "attempt", "max_attempts", "delay", "exception_type"}


def test_other_module_results_stay_unchanged(playground: int) -> None:
    config = _run(playground, "config")
    assert config["result"] == {
        "name": "playground",
        "enabled": True,
        "workers": 8,
        "timeout": 1.75,
    }
    assert "restored" in config["note"]

    http = _run(playground, "http")
    assert http["result"] == [
        {"method": "GET", "status": 503, "allowed": True},
        {"method": "POST", "status": 503, "allowed": False},
        {"method": "POST", "status": 503, "unsafe_opt_in": True, "allowed": True},
        {"method": "GET", "status": 404, "allowed": False},
    ]
    assert "No HTTP request is sent." in http["summary"]

    cache = _run(playground, "cache")
    assert cache["result"] == {
        "first_read": {"user": "Ava"},
        "after_lru_eviction": {"A": True, "B": False, "C": True},
        "expired_after_seconds": 5,
        "session_A_expired": False,
        "remaining_entries": 1,
        "stats": {"hits": 1, "misses": 0, "evictions": 1},
    }

    testing = _run(playground, "testing")
    assert testing["result"] == {
        "call_count": {"first_increment": 1, "second_increment": 2},
        "fail_then_return": {"outcomes": ["TimeoutError", "recovered"], "calls": 2},
        "fake_clock": {"start": 10, "after_advance": 12.5},
        "recorded_sleeps": [0.25, 0.5],
    }

    logging_payload = _run(playground, "logging")
    record = logging_payload["result"]
    assert record["logger"] == "pyforge.playground"
    assert record["level"] == "INFO"
    assert record["request_id"] == "req-demo-1042"
    assert record["operation"] == "payment.reconcile"
    assert record["component"] == "playground"
    assert record["attempt"] == 2
    assert record["message"]["event"] == "payment.reconciliation.completed"
    assert record["message"]["invoice_id"] == "INV-2048"
    assert record["message"]["api_key"] == "[REDACTED]"
    assert json.loads(logging_payload["raw"]) == record
    assert "restored" in logging_payload["note"]


def test_api_errors_name_the_failure(playground: int) -> None:
    status, payload = _json(playground, "POST", "/api/run", b'{"module":"missing"}')
    assert status == 400
    assert payload == {
        "error": "Unknown demo module",
        "message": "The requested module is not available.",
    }

    status, payload = _json(playground, "POST", "/api/run", b"{")
    assert status == 400
    assert payload["error"] == "Invalid JSON"
    assert payload["message"]

    status, payload = _json(playground, "POST", "/api/run", b"")
    assert status == 400
    assert payload["error"] == "Bad request"

    status, payload = _json(playground, "POST", "/api/missing", b"{}")
    assert status == 404
    assert payload["error"] == "Not found"
    assert payload["message"]

    status, health = _json(playground, "GET", "/api/health")
    assert status == 200
    assert health == {"status": "ok", "package": "pyforge-toolkit"}
