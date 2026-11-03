"""Local-only web playground for exercising the real PyForge package.

Run from the repository root with: python -m playground.server
The server binds only to 127.0.0.1 and exposes a fixed set of demo actions.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pyforge
from pyforge import (
    MemoryCache,
    RetryEvent,
    RetryPolicy,
    get_env,
    get_env_bool,
    get_env_float,
    get_env_int,
    retry,
    should_retry_http,
)
from pyforge.testing import CallCount, FailThenReturn, FakeClock, RecordingSleeper, temporary_env

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


def _lifecycle_event(event: RetryEvent) -> dict[str, Any]:
    return {
        "event_type": event.event_type.value,
        "attempt": event.attempt,
        "max_attempts": event.max_attempts,
        "delay": event.delay,
        "exception_type": event.exception_type,
    }


def _retry_demo() -> dict[str, Any]:
    sleeper = RecordingSleeper()
    events: list[dict[str, Any]] = []
    attempts = FailThenReturn(2, "Inventory sync completed", TimeoutError)

    def observe(event: RetryEvent) -> None:
        events.append(_lifecycle_event(event))

    @retry(
        policy=RetryPolicy(max_attempts=4, initial_delay=0.2, max_delay=1.0, multiplier=2),
        retry_on=(TimeoutError,),
        sleep=sleeper,
        random_value=lambda: 0.5,
        observer=observe,
    )
    def operation() -> str:
        return attempts()

    final_result = operation()
    return {
        "summary": "The operation recovered after two simulated timeouts.",
        "result": {
            "final_result": final_result,
            "total_attempts": attempts.count,
            "retry_delays": list(sleeper.delays),
            "lifecycle_events": events,
        },
    }


def _logging_demo() -> dict[str, Any]:
    stream = StringIO()
    logger = pyforge.get_logger(
        "pyforge.playground",
        context=pyforge.LogContext(
            request_id="req-demo-1042",
            operation="payment.reconcile",
            component="playground",
            attempt=2,
        ),
    )
    base_logger = logger.logger
    handler = logging.StreamHandler(stream)
    handler.setFormatter(pyforge.JsonFormatter())
    previous_level = base_logger.level
    previous_propagate = base_logger.propagate
    base_logger.addHandler(handler)
    base_logger.setLevel(logging.INFO)
    base_logger.propagate = False
    try:
        logger.info(
            {
                "event": "payment.reconciliation.completed",
                "invoice_id": "INV-2048",
                "api_key": "demo-secret-value",
            }
        )
    finally:
        base_logger.removeHandler(handler)
        base_logger.setLevel(previous_level)
        base_logger.propagate = previous_propagate
        handler.close()
    raw = stream.getvalue().strip()
    return {
        "summary": "A real JsonFormatter record, including context and secret redaction.",
        "result": json.loads(raw),
        "raw": raw,
        "note": "The demo logger's temporary handler and settings are restored after execution.",
    }


def _config_demo() -> dict[str, Any]:
    with temporary_env(
        {
            "PYFORGE_DEMO_NAME": "playground",
            "PYFORGE_DEMO_ENABLED": " true ",
            "PYFORGE_DEMO_WORKERS": "8",
            "PYFORGE_DEMO_TIMEOUT": "1.75",
        }
    ):
        values = {
            "name": get_env("PYFORGE_DEMO_NAME", required=True),
            "enabled": get_env_bool("PYFORGE_DEMO_ENABLED", required=True),
            "workers": get_env_int("PYFORGE_DEMO_WORKERS", required=True, minimum=1, maximum=32),
            "timeout": get_env_float(
                "PYFORGE_DEMO_TIMEOUT", required=True, minimum=0.1, maximum=10
            ),
        }
    return {
        "summary": "All four readers parsed values from a temporary environment.",
        "result": values,
        "note": "The temporary environment values are restored immediately after the demo.",
    }


def _http_demo() -> dict[str, Any]:
    cases = [
        {"method": "GET", "status": 503, "allowed": should_retry_http("GET", status_code=503)},
        {"method": "POST", "status": 503, "allowed": should_retry_http("POST", status_code=503)},
        {
            "method": "POST",
            "status": 503,
            "unsafe_opt_in": True,
            "allowed": should_retry_http("POST", status_code=503, allow_unsafe_method=True),
        },
        {"method": "GET", "status": 404, "allowed": should_retry_http("GET", status_code=404)},
    ]
    return {
        "summary": "Retry eligibility decisions only. No HTTP request is sent.",
        "result": cases,
        "note": "POST is not retried by default. Opting in does not provide idempotency.",
    }


def _observe_demo() -> dict[str, Any]:
    recorded = _retry_demo()
    return {
        "summary": "The retry observer captured each lifecycle event from a real retry run.",
        "result": recorded["result"]["lifecycle_events"],
    }


def _cache_demo() -> dict[str, Any]:
    clock = FakeClock()
    cache = MemoryCache(max_entries=2, clock=clock)
    cache.set("session:A", {"user": "Ava"}, ttl=5)
    cache.set("session:B", {"user": "Noah"})
    first = cache.get("session:A")
    cache.set("session:C", {"user": "Mia"})
    after_eviction = {
        "A": "session:A" in cache,
        "B": "session:B" in cache,
        "C": "session:C" in cache,
    }
    clock.advance(5)
    expired = "session:A" in cache
    stats = cache.stats()
    return {
        "summary": "A real MemoryCache demonstrates LRU eviction and monotonic TTL expiry.",
        "result": {
            "first_read": first,
            "after_lru_eviction": after_eviction,
            "expired_after_seconds": 5,
            "session_A_expired": expired,
            "remaining_entries": len(cache),
            "stats": {
                "hits": stats.hits,
                "misses": stats.misses,
                "evictions": stats.evictions,
            },
        },
        "note": "The clock is fake, so this demo runs instantly and never waits five seconds.",
    }


def _testing_demo() -> dict[str, Any]:
    counter = CallCount()
    first = counter.increment()
    second = counter.increment()
    scripted = FailThenReturn(1, "recovered")
    outcomes: list[str] = []
    for _ in range(2):
        try:
            outcomes.append(scripted())
        except TimeoutError:
            outcomes.append("TimeoutError")
    clock = FakeClock(start=10)
    clock.advance(2.5)
    sleeper = RecordingSleeper()
    sleeper(0.25)
    sleeper(0.5)
    return {
        "summary": "The test helpers run without real sleeps or wall-clock delays.",
        "result": {
            "call_count": {"first_increment": first, "second_increment": second},
            "fail_then_return": {"outcomes": outcomes, "calls": scripted.count},
            "fake_clock": {"start": 10, "after_advance": clock.now},
            "recorded_sleeps": list(sleeper.delays),
        },
        "note": "These helpers are imported from pyforge.testing, not the pyforge root namespace.",
    }


DEMOS = {
    "retry": _retry_demo,
    "logging": _logging_demo,
    "config": _config_demo,
    "http": _http_demo,
    "observe": _observe_demo,
    "cache": _cache_demo,
    "testing": _testing_demo,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "PyForgePlayground/1.0"

    def _send(self, status: int, payload: object, content_type: str = "application/json") -> None:
        body = (
            payload
            if isinstance(payload, bytes)
            else (json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        )
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send(200, {"status": "ok", "package": "pyforge-toolkit"})
            return
        if path in ("/", "/index.html"):
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html")
            return
        if path == "/app.js":
            self._send(200, (STATIC / "app.js").read_bytes(), "text/javascript")
            return
        if path == "/styles.css":
            self._send(200, (STATIC / "styles.css").read_bytes(), "text/css")
            return
        self._send(404, {"error": "Not found"})

    def _client_error(self, error: str, message: str) -> None:
        self._send(400, {"error": error, "message": message})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/run":
            self._send(
                404,
                {"error": "Not found", "message": "The requested path is not available."},
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._client_error("Bad request", "Content-Length is not an integer.")
            return
        if length < 1 or length > 10_000:
            self._client_error("Bad request", "Request body must be between 1 and 10000 bytes.")
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._client_error("Invalid JSON", "The request body is not valid JSON.")
            return
        module = payload.get("module") if isinstance(payload, dict) else None
        if not isinstance(module, str) or module not in DEMOS:
            self._client_error("Unknown demo module", "The requested module is not available.")
            return
        try:
            self._send(200, {"module": module, **DEMOS[module]()})
        except Exception as exc:
            self._send(500, {"error": type(exc).__name__, "message": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    address = ("127.0.0.1", 8765)
    server = ThreadingHTTPServer(address, Handler)
    print("PyForge Playground is running.")
    print("Open http://127.0.0.1:8765 in your browser.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PyForge Playground.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
