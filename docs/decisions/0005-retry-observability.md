# ADR 0005: Optional retry lifecycle events

- Status: Accepted
- Date: 2026-11-03

## Context

Applications need counters and diagnostic logs for retries. The package
already has a bounded retry engine and a JSON formatter. A metrics or tracing
library would be a runtime dependency and a second product. A global observer
registry would hide who receives events.

The event also has to be safe to log. Exception messages and HTTP bodies can
contain credentials.

## Decision

Add a frozen `RetryEvent` and an optional synchronous `observer` argument on
`retry`. `retry_http` forwards that same argument into `retry` and does not
emit its own events.

Three event types are enough:

- `scheduled`: a matching failure will be retried. The event is emitted after
  the delay is calculated and before sleep.
- `succeeded`: an attempt after the first one returned. A first-attempt
  success emits nothing, so a success event always means a retry occurred.
- `exhausted`: the final allowed attempt failed. The original exception is
  then re-raised.

The event stores the exception class name, not the exception object and not
`str(exc)`. Carrying the object would let an observer read a message such as
`password=supersecret`. The class name is enough to group failures. The delay
is included only on `scheduled`, and it is the exact value passed to sleep.

If the observer raises `Exception`, the engine discards it. The attempt
counter, delay, return value, and application exception stay as they were.
Discarding is deliberate: instrumentation must not turn a successful call
into a failure or hide the operation's timeout behind a metrics bug. The
engine does not log the discarded exception, because it does not configure
logging. `BaseException` from the observer, including cancellation and
keyboard interrupt, still propagates.

There is no process-wide observer list.

## Alternatives

- Passing the exception object was rejected because its message can contain
  secrets, and the observer would then be responsible for redacting it.
- Letting observer exceptions propagate on the exhausted path was rejected
  because that would replace the application's exception.
- Letting them propagate on success was rejected because the caller would
  lose a successful result.
- An async observer was rejected. The callback is synchronous so the same
  function works for sync and async operations. A blocking observer can still
  block an async caller; that is the caller's choice.
- OpenTelemetry, Prometheus, and statsd clients were rejected. The callback
  is the integration point.

## Consequences

### Positive

- Applications can count scheduled, succeeded, and exhausted outcomes without
  reading private retry state.
- Existing callers that omit `observer` keep the previous control flow.
- HTTP retries do not double-count, because only one decorator emits events.
- Events can be passed to `get_logger` without copying an exception message
  into the log line.

### Trade-offs

- A buggy observer fails quietly unless it raises `BaseException`.
- HTTP events say `RetryableHTTPStatus`, not the original transport class.
  The status code is not a field. `should_retry_http` remains the decision
  API and does not emit events.
- This is not a trace span and not a metrics backend. Callers wire those
  systems themselves.
