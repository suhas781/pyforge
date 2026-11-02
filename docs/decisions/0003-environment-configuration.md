# ADR 0003: Environment-backed configuration

- Status: Accepted
- Date: 2026-11-03

## Context

Milestone 3 needs a way to read process environment variables with explicit
types and bounds. Service settings often include credentials. A configuration
framework that loads `.env` files, caches values, or logs the environment
would hide when data is read and could copy secrets into errors or logs.

The library already has a small retry API and a JSON formatter with a narrow
redaction policy. Configuration should follow the same rule: standard library
only, no hidden global behavior.

## Decision

Add four functions: `get_env`, `get_env_bool`, `get_env_int`, and
`get_env_float`. Each call reads `os.environ` and returns. There is no
registry, cache, or import-time read.

`get_env` returns the stored string. Typed readers strip surrounding
whitespace. Booleans accept only `true`, `1`, `yes`, `on`, `false`, `0`,
`no`, and `off`, without case. Integers are optional-sign decimal digits.
Floats also allow a decimal point and an exponent, and reject non-finite
values. Numeric bounds are inclusive.

Missing required variables raise `MissingEnvironmentError`. An empty required
string does too. Invalid text and invalid defaults raise
`InvalidEnvironmentError`. Out-of-range numbers raise
`OutOfRangeEnvironmentError`, which is a `ValueError` but not a subclass of
`InvalidEnvironmentError`. Messages include the variable name and the expected
type or bounds. They omit the stored value and the default.

Automatic `.env` loading is excluded. A file in the working directory is not
part of the process environment unless the caller puts it there. Loading it
inside the library would make tests depend on the machine and could read
secrets the caller did not pass in.

## Alternatives

- `pydantic-settings` was rejected because it is a runtime dependency and a
  larger configuration framework than this milestone needs.
- A mutable settings object was rejected because it would cache values and
  create global state.
- Treating every blank string as missing was rejected for `get_env`. The
  stored string stays intact, and only an exact empty string fails a required
  string read. Typed readers still reject blank text as invalid.

## Consequences

### Positive

- Callers can see exactly when the environment is read.
- Tests can use `monkeypatch` without a process-wide settings object.
- Exception text is safe to log through `JsonFormatter` because it does not
  contain the value.

### Trade-offs

- Returned values are not redacted. Logging a database URL or token is the
  caller's decision. `JsonFormatter` still applies only its existing text
  patterns.
- There is no nested configuration, file loader, or prefix scanner.
- Platform environment lookup is unchanged: Windows names are
  case-insensitive and POSIX names are case-sensitive.
