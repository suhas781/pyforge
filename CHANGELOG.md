# Changelog

PyForge uses semantic versioning once a stable public API exists. No Git tag
has been published, and this project has not been uploaded to PyPI.

## Unreleased

### Added

- `pyforge.testing` with `FakeClock`, `RecordingSleeper`,
  `AsyncRecordingSleeper`, `CallCount`, `FailThenReturn`, `ClockedCache`, and
  `temporary_env`. Importing `pyforge` does not load these helpers. They do
  not sleep, patch the standard library, or add a runtime dependency.
- `MemoryCache` and `CacheStats` for a process-local LRU cache. Entries may
  expire after a monotonic TTL. `max_entries` bounds the count. There is no
  background thread, persistence, or shared cache. A stored `None` is present.
  A missing or expired key is not.
- `RetryEvent`, `RetryEventType`, and an optional `observer` for `retry` and
  `retry_http`. Events report a scheduled retry, a later success, or an
  exhausted attempt. The first successful attempt emits nothing. Events carry
  the exception class name, not the message. An `Exception` from the observer
  is discarded.
- `retry_http`, `should_retry_http`, and `raise_for_retryable_status` for HTTP
  retry decisions. They reuse `RetryPolicy` and do not send requests.
  Non-idempotent methods are not retried unless the caller opts in.
- `get_env`, `get_env_bool`, `get_env_int`, and `get_env_float` for one-shot
  environment reads. There is no `.env` loader and no cached configuration.
- `MissingEnvironmentError`, `InvalidEnvironmentError`, and
  `OutOfRangeEnvironmentError`. Error text omits the stored value.
- `JsonFormatter`, `LogContext`, and `get_logger` for JSON logs.
- UTC timestamps, level, logger name, message, optional context fields, and
  exception type, message, and traceback.
- Documented redaction for the sensitive field names, suffixes, and text
  patterns listed in the security notes. Unsupported extra fields are omitted.

## 0.1.0 — 2026-11-02

Alpha on `main`. This is the current library, not a production certification.

### Added

- `RetryPolicy` and `@retry` for synchronous and asynchronous callables.
- Validated attempt limits, exponential backoff, jitter, and injectable sleep
  and randomness.
- Deterministic tests for retry behavior, cancellation, and configuration
  errors.
- Package metadata, a typed package marker, and a GitHub Actions workflow for
  Python 3.11, 3.12, and 3.13.
- API reference, security notes, and distribution checks for the wheel and
  source distribution.

### Not included

- An HTTP client, socket timeouts, exactly-once request execution, and a
  metrics or tracing backend.
- A tagged release. Logging, configuration, and HTTP decisions are listed
  under Unreleased.
