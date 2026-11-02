# ADR 0006: Process-local memory cache

- Status: Accepted
- Date: 2026-11-03

## Context

Callers need a small place to reuse an expensive lookup inside one process.
A distributed cache would add a service, a client library, and consistency
rules this package does not own. A background cleanup thread would make tests
depend on scheduling and would keep running after the caller was finished.

Expiration has to be testable without sleeping. Wall-clock time jumps when
the system clock is corrected, so it is a poor TTL source.

## Decision

Add `MemoryCache`, a synchronous cache owned by the caller.

- Values are stored by identity. The cache does not copy them.
- A stored `None` is present. A missing or expired key is not `None`.
- `ttl=None` does not expire. A positive `ttl` is measured from the monotonic
  clock reading taken by that `set`. `get` does not extend it. `ttl=0` is
  already expired and is not stored. Negative, boolean, non-numeric, and
  non-finite TTLs raise.
- The default clock is `time.monotonic`. Tests inject a callable. The clock
  is called before the cache takes its lock.
- Expired entries are removed by the next `get`, `set`, `delete`, `in`, or
  `len`. There is no cleanup thread.
- Capacity is an entry count. The eviction policy is LRU, implemented with
  `OrderedDict`: `get` and a replacement `set` move a key to the newest end,
  and a new key over capacity removes the oldest live entry. `in` does not
  change order. Expiration, `delete`, and `clear` are not evictions.
- One `threading.Lock` guards the mapping and the counters for a single
  operation. The cache does not make a later `get` plus `set` atomic.
- `CacheStats` is a frozen snapshot. `reset_stats` zeros counters without
  dropping entries. `clear` drops entries without zeroing counters.
- The missing-key `KeyError` does not include the key.
- There is no global cache, persistence, encryption, or network client.

## Alternatives

- Wall-clock TTL: rejected because NTP steps and local time changes make
  tests and expiration unpredictable.
- A sliding TTL on `get`: rejected because a hot key would stay forever
  without an explicit `set`.
- FIFO eviction: simpler, but a frequently used entry would be dropped just
  because it was inserted first. LRU needs one ordered mapping and gives a
  predictable recency rule.
- Size in bytes: rejected because Python object size is not a stable measure
  of retained memory, and the caller already chooses what to store.
- An eviction callback: rejected. It would be another user function to order
  against the lock, and this milestone does not need it.
- Redis, Memcached, or an async cache: rejected. They are different products
  and would add runtime dependencies.

## Consequences

The cache is useful for short-lived process-local memoization. It is the
wrong place for data that must survive a restart, stay consistent across
processes, or be revoked everywhere at once.

`max_entries` does not cap bytes. Large values can still exhaust memory.

Key `__hash__` and `__eq__` run while the lock is held. A key that calls back
into the same cache can deadlock. The clock callback does not run under that
lock.

A clock that moves backward delays expiration. The cache does not correct it.

Individual operations are serialized per instance. Two threads can both
observe a miss and both call `set`. The later `set` wins.
