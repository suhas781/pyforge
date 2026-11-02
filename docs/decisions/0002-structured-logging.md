# ADR 0002: Structured logging with the standard library

- Status: Accepted
- Date: 2026-11-02

## Context

Milestone 2 needs JSON logs for retries and later service calls. The records
need a timestamp, level, logger name, message, a few context fields, and
exception details. The library must not configure the root logger on import,
and it must not take a runtime dependency for logging.

Arbitrary `extra` dictionaries would make it easy to write passwords, tokens,
and authorization headers into a log line.

## Decision

Use `logging.Formatter` and `logging.LoggerAdapter`.

`JsonFormatter` emits one JSON object. It always includes `timestamp` in UTC,
`level`, `logger`, and `message`. It includes `request_id`, `operation`,
`component`, and a non-negative integer `attempt` only when those attributes
are present. Every other record attribute is omitted.

`LogContext` accepts only those four fields. `get_logger` binds a context to
an adapter and does not attach handlers or change propagation.

Sensitive mapping keys are replaced with `[REDACTED]` using the public name
and suffix lists. Messages, context strings, and exception text use the
authorization, bearer, and `name=value` patterns documented in
`docs/security.md`. Unserializable values use the type name instead of
`repr`.

## Alternatives

- structlog was rejected because it would be a runtime dependency.
- Copying `LogRecord.__dict__` into JSON was rejected because unknown extras
  would be serialized.
- Heuristic entropy scanning was rejected because its guarantees would be
  broader than the tests.

## Consequences

### Positive

- Formatting is deterministic and uses the standard library.
- Importing the package does not change root logging.
- The redaction guarantee is the same list the tests lock.

### Trade-offs

- A secret that does not match a listed key, suffix, or text pattern is not
  detected. CamelCase names such as `sessionToken` are not split.
- Context fields are identifiers. A raw secret placed in `component` is
  logged unless its text matches a pattern.
- Callers still choose handlers and levels. PyForge does not install them.
