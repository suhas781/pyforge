# Changelog

PyForge uses semantic versioning once a stable public API exists. The source
tree declares version `0.1.0`. No Git tag has been published, and this
project has not been uploaded to PyPI. The `0.1.0` section describes the
capabilities in that source tree. It is not a release announcement.

## Unreleased

No changes are waiting beyond the `0.1.0` source tree. Put future work here.

## 0.1.0 — 2026-11-02

Version identifier in the source tree. This heading is not a Git tag and not
a PyPI release. `2026-11-02` is the date that version identifier was recorded.
It is not a publication date for the capabilities below.

### Added

- `RetryPolicy` and `@retry` for synchronous and asynchronous callables, with
  validated attempt limits, exponential backoff, jitter, and injectable sleep
  and randomness.
- `JsonFormatter`, `LogContext`, and `get_logger` for one JSON object per
  record. Redaction is limited to the names, suffixes, and text patterns in
  the security notes.
- `get_env`, `get_env_bool`, `get_env_int`, and `get_env_float` for one-shot
  environment reads. There is no `.env` loader and no cached configuration.
- `MissingEnvironmentError`, `InvalidEnvironmentError`, and
  `OutOfRangeEnvironmentError`. Error text omits the stored value.
- `retry_http`, `should_retry_http`, and `raise_for_retryable_status` for HTTP
  retry decisions. They reuse `RetryPolicy` and do not send requests.
  Non-idempotent methods are not retried unless the caller opts in.
- `RetryEvent`, `RetryEventType`, and an optional `observer` for `retry` and
  `retry_http`. The first successful attempt emits nothing. Events carry the
  exception class name, not the message. An `Exception` from the observer is
  discarded.
- `MemoryCache` and `CacheStats` for a process-local LRU cache. Entries may
  expire after a monotonic TTL. `max_entries` bounds the count. There is no
  background thread, persistence, or shared cache. A stored `None` is present.
  A missing or expired key is not.
- `pyforge.testing` with `FakeClock`, `RecordingSleeper`,
  `AsyncRecordingSleeper`, `CallCount`, `FailThenReturn`, `ClockedCache`, and
  `temporary_env`. Importing `pyforge` does not load these helpers. They do
  not sleep, patch the standard library, or add a runtime dependency.
- The version string `0.1.0` in `pyproject.toml` and `pyforge.__version__`.

Repository tools. These are not part of the installed `pyforge` wheel:

- Release checklist in `docs/releasing.md`. Project metadata records the
  repository URLs. The license remains the `MIT` expression. CI does not tag
  or publish.
- `scripts/audit_installed_packages.py` queries the OSV database for installed
  third-party packages, and CI runs that script. `pyforge-toolkit` is skipped
  because it is not on PyPI. A response with no advisories is not a claim that
  no vulnerabilities exist.
- `actions/checkout` and `actions/setup-python` are pinned to commit SHAs.
  The workflow permission remains `contents: read`.
- `playground/` is a local development server for fixed demonstrations. It
  binds to `127.0.0.1:8765`, has no authentication, and is not a public
  deployment.

### Not included

- A tagged release or a PyPI upload.
- An HTTP client, socket timeouts, exactly-once request execution, and a
  metrics or tracing backend.
