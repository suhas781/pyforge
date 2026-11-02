"""Deterministic tests for the in-memory cache."""

from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import pytest

from pyforge import CacheStats, MemoryCache


class Clock:
    """A monotonic stand-in. Tests move ``now`` instead of sleeping."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_set_and_get_return_the_same_object() -> None:
    cache = MemoryCache(2, clock=Clock())
    value = {"status": "ok"}
    cache.set("profile", value)
    assert cache.get("profile") is value
    value["status"] = "changed"
    assert cache.get("profile")["status"] == "changed"


def test_update_replaces_value_and_refreshes_ttl() -> None:
    clock = Clock()
    cache = MemoryCache(2, clock=clock)
    cache.set("profile", "old", ttl=5)
    clock.now = 4
    cache.set("profile", "new", ttl=5)
    clock.now = 8
    assert cache.get("profile") == "new"
    clock.now = 9
    assert "profile" not in cache


def test_get_does_not_extend_ttl() -> None:
    clock = Clock()
    cache = MemoryCache(2, clock=clock)
    cache.set("profile", "value", ttl=5)
    clock.now = 4
    assert cache.get("profile") == "value"
    clock.now = 5
    with pytest.raises(KeyError, match="missing or expired"):
        cache.get("profile")


def test_missing_key_raises_and_counts_a_miss() -> None:
    cache = MemoryCache(2, clock=Clock())
    secret = "password=supersecret"
    with pytest.raises(KeyError, match="missing or expired") as caught:
        cache.get(secret)
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert caught.value.args == ("cache entry is missing or expired",)
    rendered = "".join(traceback.format_exception(caught.value))
    assert secret not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert cache.stats() == CacheStats(hits=0, misses=1, evictions=0)


def test_default_is_returned_for_a_miss_and_is_not_stored() -> None:
    cache = MemoryCache(2, clock=Clock())
    assert cache.get("missing", "fallback") == "fallback"
    assert "missing" not in cache
    assert cache.stats().misses == 1
    cache.set("present", 1)
    assert cache.get("present", "fallback") == 1


def test_cached_none_is_a_hit() -> None:
    cache = MemoryCache(2, clock=Clock())
    cache.set("empty", None)
    assert "empty" in cache
    assert cache.get("empty") is None
    assert cache.get("empty", "fallback") is None
    assert cache.stats() == CacheStats(hits=2, misses=0, evictions=0)


def test_expiration_uses_the_injected_clock() -> None:
    clock = Clock(10)
    cache = MemoryCache(2, clock=clock)
    cache.set("profile", "value", ttl=5)
    clock.now = 14.999
    assert cache.get("profile") == "value"
    clock.now = 15
    assert "profile" not in cache
    assert len(cache) == 0
    with pytest.raises(KeyError, match="missing or expired"):
        cache.get("profile")
    assert cache.stats().misses == 1
    assert cache.stats().evictions == 0


def test_zero_ttl_is_not_stored_and_removes_an_existing_key() -> None:
    cache = MemoryCache(1, clock=Clock())
    cache.set("keep", "value")
    cache.set("temp", "gone", ttl=0)
    assert cache.get("keep") == "value"
    cache.set("keep", "value", ttl=0)
    assert "keep" not in cache
    assert cache.stats().evictions == 0


def test_permanent_entry_survives_a_later_clock_reading() -> None:
    clock = Clock()
    cache = MemoryCache(2, clock=clock)
    cache.set("profile", "value")
    cache.set("temp", "gone", ttl=1)
    clock.now = 1
    assert cache.get("profile") == "value"
    assert "temp" not in cache


def test_expired_entries_do_not_consume_capacity() -> None:
    clock = Clock()
    cache = MemoryCache(1, clock=clock)
    cache.set("old", "value", ttl=1)
    clock.now = 1
    cache.set("new", "value")
    assert cache.get("new") == "value"
    assert cache.stats().evictions == 0


def test_lru_evicts_the_least_recently_used_live_entry() -> None:
    cache = MemoryCache(2, clock=Clock())
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    cache.set("c", 3)
    assert "b" not in cache
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.stats().evictions == 1


def test_membership_does_not_refresh_lru_order() -> None:
    cache = MemoryCache(2, clock=Clock())
    cache.set("a", 1)
    cache.set("b", 2)
    assert "a" in cache
    cache.set("c", 3)
    assert "a" not in cache
    assert cache.get("b") == 2
    assert cache.stats().hits == 1
    assert cache.stats().misses == 0


def test_update_refreshes_lru_order_without_an_eviction() -> None:
    cache = MemoryCache(2, clock=Clock())
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("a", 9)
    cache.set("c", 3)
    assert cache.get("a") == 9
    assert "b" not in cache
    assert cache.stats().evictions == 1


def test_delete_clear_and_reset_have_distinct_effects() -> None:
    cache = MemoryCache(2, clock=Clock())
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.delete("b") is True
    assert cache.delete("missing") is False
    assert cache.stats().evictions == 1
    snapshot = cache.stats()
    cache.clear()
    assert len(cache) == 0
    assert cache.stats() == snapshot
    cache.reset_stats()
    assert cache.stats() == CacheStats(0, 0, 0)
    assert snapshot.evictions == 1


def test_delete_of_an_expired_key_returns_false() -> None:
    clock = Clock()
    cache = MemoryCache(2, clock=clock)
    cache.set("a", 1, ttl=1)
    clock.now = 1
    assert cache.delete("a") is False
    assert cache.stats().evictions == 0


def test_stats_snapshot_does_not_change_later() -> None:
    cache = MemoryCache(1, clock=Clock())
    cache.set("a", 1)
    cache.get("a")
    snapshot = cache.stats()
    cache.get("missing", None)
    assert snapshot == CacheStats(1, 0, 0)
    assert cache.stats().misses == 1


def test_backwards_clock_does_not_expire_early() -> None:
    clock = Clock(10)
    cache = MemoryCache(1, clock=clock)
    cache.set("a", 1, ttl=5)
    clock.now = 0
    assert cache.get("a") == 1


def test_stored_exception_is_returned_not_raised() -> None:
    cache = MemoryCache(1, clock=Clock())
    error = ValueError("boom")
    cache.set("error", error)
    assert cache.get("error") is error


def test_caches_do_not_share_entries() -> None:
    first = MemoryCache(1, clock=Clock())
    second = MemoryCache(1, clock=Clock())
    first.set("a", 1)
    assert "a" not in second


def test_default_clock_is_monotonic() -> None:
    cache = MemoryCache(1)
    assert cache._clock is time.monotonic
    cache.set("a", 1)
    assert cache.get("a") == 1


def test_invalid_max_entries_and_ttl_and_clock() -> None:
    with pytest.raises(TypeError, match="integer"):
        MemoryCache(True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer"):
        MemoryCache(1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least 1"):
        MemoryCache(0)
    with pytest.raises(TypeError, match="callable"):
        MemoryCache(1, clock=1)  # type: ignore[arg-type]

    cache = MemoryCache(1, clock=Clock())
    for ttl in (True, "5", object()):
        with pytest.raises(TypeError, match="real number"):
            cache.set("a", 1, ttl=ttl)  # type: ignore[arg-type]
    for ttl in (-1, math.nan, math.inf, -(10**400), 10**400):
        with pytest.raises(ValueError, match="finite"):
            cache.set("a", 1, ttl=ttl)
    assert len(cache) == 0

    with pytest.raises(TypeError):
        cache.set(["mutable"], 1)  # type: ignore[arg-type]


def test_invalid_clock_readings_do_not_change_entries() -> None:
    clock = Clock()
    cache = MemoryCache(1, clock=clock)
    cache.set("a", 1)
    clock.now = math.nan
    with pytest.raises(ValueError, match="finite"):
        cache.get("a")
    clock.now = True  # type: ignore[assignment]
    with pytest.raises(TypeError, match="real number"):
        len(cache)
    clock.now = "later"  # type: ignore[assignment]
    with pytest.raises(TypeError, match="real number"):
        cache.delete("a")
    clock.now = 10**400
    with pytest.raises(ValueError, match="finite"):
        cache.get("a")
    clock.now = 0
    assert cache.get("a") == 1


def test_clock_is_called_without_the_cache_lock() -> None:
    seen: list[bool] = []
    cache_holder: list[MemoryCache] = []

    def clock() -> float:
        seen.append(cache_holder[0]._lock.locked())
        return 0.0

    cache = MemoryCache(1, clock=clock)
    cache_holder.append(cache)
    cache.set("a", 1, ttl=5)
    assert cache.get("a") == 1
    assert "a" in cache
    assert len(cache) == 1
    assert cache.delete("a") is True
    assert seen
    assert seen == [False] * len(seen)


def test_operations_start_no_background_thread() -> None:
    before = threading.active_count()
    cache = MemoryCache(2, clock=Clock())
    cache.set("a", 1, ttl=1)
    cache.get("a")
    cache.clear()
    assert threading.active_count() == before


def test_concurrent_operations_stay_within_capacity() -> None:
    cache = MemoryCache(8, clock=lambda: 0.0)
    errors: list[BaseException] = []

    def worker(worker_id: int) -> None:
        try:
            for index in range(40):
                key = (worker_id, index % 8)
                cache.set(key, index, ttl=None)
                cache.get(key, None)
                if index % 4 == 0:
                    cache.delete(key)
                if key in cache:
                    assert len(cache) <= cache.max_entries
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(item,)) for item in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(cache) <= cache.max_entries
    stats = cache.stats()
    assert stats.hits >= 0
    assert stats.misses >= 0
    assert stats.evictions >= 0


def test_operations_do_not_change_environment_or_logging() -> None:
    before = dict(os.environ)
    root = logging.getLogger()
    snapshot = (root.level, list(root.handlers), root.disabled)
    cache = MemoryCache(1, clock=Clock())
    cache.set("token", "secret")
    assert cache.get("token") == "secret"
    assert dict(os.environ) == before
    assert (root.level, list(root.handlers), root.disabled) == snapshot


def test_import_does_not_change_environment_or_logging(tmp_path: Path) -> None:
    script = tmp_path / "check_cache_import.py"
    script.write_text(
        "\n".join(
            (
                "import logging",
                "import os",
                "before = dict(os.environ)",
                "root = logging.getLogger()",
                "snapshot = (root.level, list(root.handlers), root.disabled)",
                "import pyforge.cache",
                "cache = pyforge.cache.MemoryCache(1, clock=lambda: 0.0)",
                "cache.set('k', None)",
                "assert cache.get('k') is None",
                "assert dict(os.environ) == before",
                "assert (root.level, list(root.handlers), root.disabled) == snapshot",
            )
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_integer_clock_and_ttl_are_accepted() -> None:
    readings = iter((1, 1, 3))

    def clock() -> int:
        return next(readings)

    cache = MemoryCache(1, clock=clock)
    cache.set(("user", 7), "value", ttl=2)
    assert cache.get(("user", 7)) == "value"
    assert ("user", 7) not in cache
