# ADR 0007: Deterministic test helpers

- Status: Accepted
- Date: 2026-11-03

## Context

Application tests need to move time, record retry delays, count attempts, and
set environment variables without sleeping or leaving process state behind.
The production modules already accept an injected clock and an injected sleep
callable. A second retry implementation, or a patch of `time.sleep`, would
hide the real integration and could leak into production imports.

The helpers also have to stay out of the ordinary import of `pyforge`. A
logging or configuration caller should not load test utilities as a side
effect.

## Decision

Add `pyforge.testing` inside the same distribution. The package root does not
import it. There is no extra install and no runtime dependency.

The public helpers are:

- `FakeClock`: a lock-protected number that starts at a finite value and
  moves only when `advance` is called. Negative starts are allowed. Advances
  are finite and at least zero. It does not read `time.monotonic`.
- `ClockedCache`: a `MemoryCache` paired with the `FakeClock` it reads.
  Tests expire entries by advancing that clock. Cache internals stay private.
- `RecordingSleeper`: a synchronous `retry` sleep callable. It appends the
  requested delay and returns. `AsyncRecordingSleeper` is a separate callable
  whose returned coroutine finishes immediately. The delay is recorded at the
  call, before that coroutine runs.
- `CallCount` and `FailThenReturn`: instance-local attempt state.
  `FailThenReturn` raises an exception type constructed with no arguments,
  then returns a prepared result. There is no global counter.
- `temporary_env`: a context manager for selected environment names. `None`
  removes a name. Exit restores the previous value, or removes the name if it
  was absent, including when the block raises. An empty string is distinct
  from absence. Names the block creates outside the mapping are left set.

Invalid numbers, counts, exception types, and environment entries raise
`TypeError` or `ValueError`. Those messages do not include environment names
or values.

The helpers do not patch the standard library.

## Alternatives

- Patch `time.sleep` and `os.environ` globally: rejected. A forgotten patch
  leaks into other tests, and an async retry would still need an awaitable.
- Put the helpers on the `pyforge` root: rejected. Production imports would
  load test-only code.
- A separate distribution: rejected. It would add packaging and version
  coupling for a few classes that use only the standard library and
  `MemoryCache`.
- A pytest plugin: rejected. The helpers should work in any test runner, and
  PyForge does not need to own fixtures or collection.

## Consequences

Tests can drive retry and cache behavior without real time. They pass the
sleeper or clock in, which is the same extension point production code uses
for tests.

`temporary_env` is not thread-safe. The process environment is shared, and
the helper does not lock it. Two threads that change the same name can
restore the wrong value. Other helpers lock only their own instance state.

`FakeClock` can move backward relative to a previous test's wall clock
because it is an independent number. A negative `advance` is rejected, so one
clock does not move backward after it starts.

`FailThenReturn` cannot raise an exception that requires constructor
arguments. A test that needs a message writes its own callable and counts
with `CallCount`.
