# Changelog

PyForge uses semantic versioning once a stable public API exists. No Git tag
has been published, and this project has not been uploaded to PyPI.

## Unreleased

### Added

- `get_env`, `get_env_bool`, `get_env_int`, and `get_env_float` for one-shot
  environment reads. There is no `.env` loader, cache, or global registry.
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

- HTTP retries.
- A tagged release. Structured logging and environment configuration are listed
  under Unreleased.
