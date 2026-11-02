# Changelog

PyForge uses semantic versioning once a stable public API exists. No Git tag
has been published, and this project has not been uploaded to PyPI.

## Unreleased

### Added

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

- Environment configuration helpers and HTTP retries.
- A tagged release. Structured logging is listed under Unreleased.
