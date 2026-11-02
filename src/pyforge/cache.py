"""A bounded in-memory cache with explicit expiration.

Each instance owns its entries. There is no process-wide cache, no
background thread, and no persistence. Time-to-live uses a monotonic clock,
not the wall clock. The default clock is ``time.monotonic``.

``get`` returns the stored object itself. The cache does not copy values, so
mutating a stored list or dict mutates the cached object. A stored ``None``
is a present value. A missing or expired key is not ``None``.

The clock is called without holding the cache lock. Key hashing and equality
still run while the lock is held, because that is how the mapping lookup
works. Those methods must not call back into the same cache.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import cast

_MISSING = object()


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Snapshot of cache counters.

    ``evictions`` counts live entries removed to stay within ``max_entries``.
    Expiration, ``delete``, and ``clear`` are not evictions. The snapshot does
    not change when the cache is used again.
    """

    hits: int
    misses: int
    evictions: int


class MemoryCache:
    """Thread-safe LRU cache with optional per-entry expiration.

    ``max_entries`` is at least 1. ``ttl`` on ``set`` is seconds from the
    clock reading taken for that call. ``None`` means the entry does not
    expire. ``get`` does not extend a TTL. An update replaces the value, the
    TTL, and the LRU position.

    An entry is expired when ``clock() >= inserted_clock + ttl``. A zero TTL
    is already expired at insertion and is not stored. Expired entries are
    removed on ``get``, ``set``, ``delete``, ``in``, and ``len``. Nothing
    scans the cache in the background.
    """

    def __init__(
        self,
        max_entries: int,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max_entries = _max_entries(max_entries)
        self._clock = time.monotonic if clock is None else _clock(clock)
        self._lock = threading.Lock()
        self._entries: OrderedDict[Hashable, tuple[object, float | None]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def max_entries(self) -> int:
        """Maximum number of live entries."""
        return self._max_entries

    def set(self, key: Hashable, value: object, *, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``.

        A later ``set`` for the same key replaces the value and TTL. When the
        cache is full, the least recently used live entry is evicted first.
        """
        lifetime = None if ttl is None else _ttl(ttl)
        now = self._time()
        expires_at = None if lifetime is None else now + lifetime
        with self._lock:
            self._drop_expired(now)
            if expires_at is not None and now >= expires_at:
                self._entries.pop(key, None)
                return
            if key in self._entries:
                self._entries[key] = (value, expires_at)
                self._entries.move_to_end(key)
                return
            while len(self._entries) >= self._max_entries:
                self._entries.popitem(last=False)
                self._evictions += 1
            self._entries[key] = (value, expires_at)

    def get(self, key: Hashable, default: object = _MISSING) -> object:
        """Return the stored value.

        A missing or expired key raises ``KeyError`` when ``default`` is
        omitted. The error text does not include the key. A stored ``None``
        is returned as ``None`` and counts as a hit.
        """
        now = self._time()
        with self._lock:
            self._drop_expired(now)
            if key not in self._entries:
                self._misses += 1
                if default is _MISSING:
                    raise KeyError("cache entry is missing or expired")
                return default
            value, _expires_at = self._entries[key]
            self._entries.move_to_end(key)
            self._hits += 1
            return value

    def delete(self, key: Hashable) -> bool:
        """Remove one live key.

        Returns ``True`` when a live entry was removed. A missing or expired
        key returns ``False``.
        """
        now = self._time()
        with self._lock:
            self._drop_expired(now)
            if key not in self._entries:
                return False
            del self._entries[key]
            return True

    def clear(self) -> None:
        """Remove every entry. Statistics are left unchanged."""
        with self._lock:
            self._entries.clear()

    def stats(self) -> CacheStats:
        """Return the current counters."""
        with self._lock:
            return CacheStats(self._hits, self._misses, self._evictions)

    def reset_stats(self) -> None:
        """Zero the counters without removing entries."""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def __contains__(self, key: object) -> bool:
        """Return whether ``key`` is present and unexpired.

        This does not count a hit or miss and does not change LRU order.
        """
        now = self._time()
        with self._lock:
            self._drop_expired(now)
            return key in self._entries

    def __len__(self) -> int:
        """Return the number of unexpired entries."""
        now = self._time()
        with self._lock:
            self._drop_expired(now)
            return len(self._entries)

    def _time(self) -> float:
        reading: object = self._clock()
        if isinstance(reading, bool) or not isinstance(reading, int | float):
            raise TypeError("clock must return a real number")
        try:
            now = float(reading)
        except OverflowError:
            raise ValueError("clock must return a finite number") from None
        if not math.isfinite(now):
            raise ValueError("clock must return a finite number")
        return now

    def _drop_expired(self, now: float) -> None:
        expired = [
            key
            for key, (_value, expires_at) in self._entries.items()
            if expires_at is not None and now >= expires_at
        ]
        for key in expired:
            del self._entries[key]


def _clock(value: object) -> Callable[[], float]:
    if not callable(value):
        raise TypeError("clock must be callable")
    return cast(Callable[[], float], value)


def _max_entries(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_entries must be an integer")
    if value < 1:
        raise ValueError("max_entries must be at least 1")
    return value


def _ttl(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("ttl must be a real number of seconds")
    try:
        ttl = float(value)
    except OverflowError:
        raise ValueError("ttl must be a finite number of seconds of at least 0") from None
    if not math.isfinite(ttl) or ttl < 0:
        raise ValueError("ttl must be a finite number of seconds of at least 0")
    return ttl
