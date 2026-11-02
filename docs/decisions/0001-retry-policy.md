# ADR 0001: Implement a small bounded retry primitive

- Status: Accepted
- Date: 2026-11-02

## Context

The portfolio needs a reusable engineering foundation demonstrating typed
interfaces, deterministic tests, and careful failure handling without hiding
behavior behind a large framework.

## Decision

Implement a standard-library-only retry decorator supporting sync and async
callables. Use an immutable policy object, explicit retryable exception types,
bounded exponential backoff, optional jitter, and injectable timing/randomness.

Catch only the configured `Exception` subclasses. Do not catch
`BaseException`. `asyncio.CancelledError` therefore propagates and is not
retried. Keep the starter default `retry_on=(Exception,)`, and document that
callers should pass a narrower tuple. Reject invalid policies and invalid
`retry_on` values before a call runs.

## Consequences

### Positive
- Runtime implementation has no third-party dependencies.
- Tests do not need real waiting.
- Callers can narrow `retry_on`; the default still retries every `Exception` subclass.
- Sync and async functions share the same policy model.

### Trade-offs
- This is not a distributed retry system.
- Callers must understand idempotency and avoid retrying unsafe operations.
- The default `retry_on` retries every `Exception` subclass, which can retry
  programming errors unless the caller narrows it.
- Jitter cannot extend a delay past `max_delay`, so the full symmetric range
  is only available below the cap.
- Circuit-breaking and rate-limiting remain out of scope.
