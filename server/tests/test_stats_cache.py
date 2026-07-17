"""Unit tests for the public stats endpoints' in-process TTL cache.

Exercises ``_cached`` directly, no DB: it's a generic single-flight
memoizer, and its correctness (hit/expiry/concurrency/error-propagation)
doesn't depend on what it wraps.
"""

import asyncio

import pytest

from speedfog_racing.api import stats as stats_module
from speedfog_racing.api.stats import _cached


async def test_second_call_returns_cached_value_without_recomputing():
    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        return 42

    first = await _cached("k1", compute)
    second = await _cached("k1", compute)

    assert first == 42
    assert second == 42
    assert calls == 1


async def test_recomputes_after_ttl_expiry(monkeypatch):
    fake_now = 1000.0
    monkeypatch.setattr(stats_module, "monotonic", lambda: fake_now)

    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        return calls

    first = await _cached("k2", compute)
    assert first == 1
    assert calls == 1

    # Still within TTL: no recompute.
    fake_now += stats_module.STATS_CACHE_TTL - 1
    second = await _cached("k2", compute)
    assert second == 1
    assert calls == 1

    # Past TTL: recompute.
    fake_now += 2
    third = await _cached("k2", compute)
    assert third == 2
    assert calls == 2


async def test_concurrent_cold_calls_compute_once():
    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    results = await asyncio.gather(
        _cached("k3", compute),
        _cached("k3", compute),
        _cached("k3", compute),
    )

    assert results == [1, 1, 1]
    assert calls == 1


async def test_different_keys_compute_independently():
    calls: dict[str, int] = {"a": 0, "b": 0}

    async def compute_a() -> str:
        calls["a"] += 1
        return "a-value"

    async def compute_b() -> str:
        calls["b"] += 1
        return "b-value"

    result_a = await _cached("key-a", compute_a)
    result_b = await _cached("key-b", compute_b)

    assert result_a == "a-value"
    assert result_b == "b-value"
    assert calls == {"a": 1, "b": 1}


async def test_raising_compute_caches_nothing():
    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("boom")
        return calls

    with pytest.raises(ValueError, match="boom"):
        await _cached("k5", compute)

    # Next call recomputes rather than replaying the failure or a cached miss.
    result = await _cached("k5", compute)
    assert result == 2
    assert calls == 2
