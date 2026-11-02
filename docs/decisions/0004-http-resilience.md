# ADR 0004: HTTP retry decisions without an HTTP client

- Status: Accepted
- Date: 2026-11-03

## Context

Milestone 4 needs safer retry decisions for HTTP calls. The package already
has a bounded retry decorator. Adding `requests`, `httpx`, `urllib3`, or
`aiohttp` would make PyForge an HTTP client and would add a runtime
dependency. A wrapper also cannot enforce a timeout that the caller's
transport does not expose.

Retrying `POST` by default would repeat writes. A client-side timeout does
not prove the server skipped the request.

## Decision

Add decision helpers and a thin decorator in `pyforge.http`. Do not open
sockets.

`is_idempotent_method` follows RFC 9110: `GET`, `HEAD`, `OPTIONS`, `PUT`,
`DELETE`, and `TRACE` are idempotent. Every other method, including `POST`
and `PATCH`, is not.

`should_retry_http` returns true only when the method is allowed and the
outcome matches the configured status set or exception tuple. The default
statuses are 408, 429, 500, 502, 503, and 504. The default exceptions are
`TimeoutError` and `ConnectionError`. `allow_unsafe_method=True` is the
explicit opt-in for a non-idempotent method. The flag does not create or
send an idempotency key.

`retry_http` calls the existing `retry` decorator. Eligible transport
exceptions are translated into `RetryableHTTPStatus`, whose message keeps
the class name and omits the original text. Status codes are raised by the
callable through `raise_for_retryable_status`, because the library has no
response object. The decorator does not take a timeout. The caller sets that
on the HTTP client.

Attempt limits, backoff, jitter, injected sleep, and cancellation stay in
`RetryPolicy` and `retry`.

## Alternatives

- Vendoring an HTTP client was rejected because the milestone is retry
  safety, not transport.
- A second backoff loop was rejected because it would drift from the tested
  retry engine.
- Retrying every `POST` that returned 503 was rejected because the server
  may already have applied the first request.
- Guessing a timeout inside PyForge was rejected. The timeout has to be a
  socket or client deadline owned by the transport.

## Consequences

### Positive

- GET retries have a small, typed default.
- POST retries require an explicit flag at the exception boundary and again
  at the status check.
- Tests can exercise the decisions without network access.
- The runtime dependency set stays empty.

### Trade-offs

- PyForge does not guarantee exactly-once execution.
- A timeout still does not describe the server's outcome.
- Method classification is by name only. A GET with server side effects is
  still treated as idempotent.
- The final error from `retry_http` is `RetryableHTTPStatus`, not the
  original transport exception. The class name is preserved on `error_type`.
- Callers who construct `RetryableHTTPStatus` themselves bypass the method
  check. That construction is an explicit retry signal.
