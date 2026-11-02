# Changelog

PyForge uses semantic versioning once a stable public API exists. No Git tag
has been published, and this project has not been uploaded to PyPI.

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

- Structured logging, environment configuration helpers, and HTTP retries.
- A tagged release.
