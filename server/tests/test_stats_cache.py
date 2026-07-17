"""Unit tests for the public stats endpoints' in-process TTL cache.

Exercises ``_cached`` directly, no DB: it's a generic single-flight
stale-while-revalidate memoizer, and its correctness (hit/expiry/
concurrency/error-propagation/background-refresh) doesn't depend on what
it wraps. The ``db`` argument is only threaded through to ``compute``, so
tests pass sentinels in its place.
"""

import asyncio

import pytest

from speedfog_racing.api import stats as stats_module
from speedfog_racing.api.stats import _cached


class FakeSessionCtx:
    """Stands in for ``async_session_maker()`` in background refreshes."""

    async def __aenter__(self):
        return "bg-session"

    async def __aexit__(self, *exc):
        return False


async def test_second_call_returns_cached_value_without_recomputing():
    calls = 0

    async def compute(db) -> int:
        nonlocal calls
        calls += 1
        return 42

    first = await _cached("k1", compute, None)
    second = await _cached("k1", compute, None)

    assert first == 42
    assert second == 42
    assert calls == 1


async def test_concurrent_cold_calls_compute_once():
    calls = 0

    async def compute(db) -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    results = await asyncio.gather(
        _cached("k3", compute, None),
        _cached("k3", compute, None),
        _cached("k3", compute, None),
    )

    assert results == [1, 1, 1]
    assert calls == 1


async def test_different_keys_compute_independently():
    calls: dict[str, int] = {"a": 0, "b": 0}

    async def compute_a(db) -> str:
        calls["a"] += 1
        return "a-value"

    async def compute_b(db) -> str:
        calls["b"] += 1
        return "b-value"

    result_a = await _cached("key-a", compute_a, None)
    result_b = await _cached("key-b", compute_b, None)

    assert result_a == "a-value"
    assert result_b == "b-value"
    assert calls == {"a": 1, "b": 1}


async def test_raising_compute_caches_nothing():
    calls = 0

    async def compute(db) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("boom")
        return calls

    with pytest.raises(ValueError, match="boom"):
        await _cached("k5", compute, None)

    # Next call recomputes rather than replaying the failure or a cached miss.
    result = await _cached("k5", compute, None)
    assert result == 2
    assert calls == 2


async def test_stale_hit_serves_old_value_and_refreshes_in_background(monkeypatch):
    fake_now = 1000.0
    monkeypatch.setattr(stats_module, "monotonic", lambda: fake_now)
    monkeypatch.setattr(stats_module, "async_session_maker", lambda: FakeSessionCtx())

    sessions: list[object] = []

    async def compute(db) -> int:
        sessions.append(db)
        return len(sessions)

    first = await _cached("swr1", compute, "request-session")
    assert first == 1

    # Within TTL: cached, no recompute.
    fake_now += stats_module.STATS_CACHE_TTL - 1
    assert await _cached("swr1", compute, "request-session") == 1
    assert len(sessions) == 1

    # Past TTL: the stale value is served immediately, no waiting on the
    # recompute, which runs in the background with its own session.
    fake_now += 2
    second = await _cached("swr1", compute, "request-session")
    assert second == 1

    await stats_module._refresh_tasks["swr1"]
    third = await _cached("swr1", compute, "request-session")
    assert third == 2
    assert sessions == ["request-session", "bg-session"]
    assert not stats_module._refresh_tasks


async def test_concurrent_stale_hits_schedule_one_refresh(monkeypatch):
    fake_now = 1000.0
    monkeypatch.setattr(stats_module, "monotonic", lambda: fake_now)
    monkeypatch.setattr(stats_module, "async_session_maker", lambda: FakeSessionCtx())

    calls = 0

    async def compute(db) -> int:
        nonlocal calls
        calls += 1
        return calls

    await _cached("swr2", compute, None)
    fake_now += stats_module.STATS_CACHE_TTL + 1

    # Two stale hits before the refresh task gets to run: one task only.
    a = await _cached("swr2", compute, None)
    b = await _cached("swr2", compute, None)
    assert (a, b) == (1, 1)
    assert len(stats_module._refresh_tasks) == 1

    await stats_module._refresh_tasks["swr2"]
    assert calls == 2


async def test_failed_refresh_keeps_stale_value(monkeypatch):
    fake_now = 1000.0
    monkeypatch.setattr(stats_module, "monotonic", lambda: fake_now)
    monkeypatch.setattr(stats_module, "async_session_maker", lambda: FakeSessionCtx())

    calls = 0

    async def compute(db) -> str:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ValueError("boom")
        return "v1"

    await _cached("swr3", compute, None)
    fake_now += stats_module.STATS_CACHE_TTL + 1

    stale = await _cached("swr3", compute, None)
    assert stale == "v1"
    await stats_module._refresh_tasks["swr3"]

    # Refresh failed: the stale value stays in place and keeps being served;
    # the next stale hit schedules a retry rather than surfacing the error.
    again = await _cached("swr3", compute, None)
    assert again == "v1"
    await stats_module._refresh_tasks["swr3"]
    assert calls == 3
