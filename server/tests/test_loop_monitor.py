"""Tests for the event-loop monitor (GC pauses and loop lag)."""

import asyncio
import gc
import logging
import re
import time

import pytest

from speedfog_racing.services.loop_monitor import EventLoopMonitor, GcPauseTracker

LAG_LINE = re.compile(r"Event loop lag: (\d+) ms \(gc (\d+) ms\)")


class ManualClock:
    """A clock the test moves by hand: real collections see no time pass."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _collect(
    tracker: GcPauseTracker,
    clock: ManualClock,
    generation: int,
    duration: float,
    collected: int = 0,
) -> None:
    tracker("start", {"generation": generation})
    clock.now += duration
    tracker("stop", {"generation": generation, "collected": collected, "uncollectable": 0})


def test_gc_tracker_measures_each_collection_and_keeps_only_slow_pauses() -> None:
    clock = ManualClock()
    tracker = GcPauseTracker(clock=clock, slow_threshold=0.25)
    _collect(tracker, clock, 0, 0.01)
    _collect(tracker, clock, 2, 0.4, collected=1234)

    window = tracker.take_window()
    slow = tracker.drain_slow_pauses()

    assert window.counts == {0: 1, 2: 1}
    assert window.total == pytest.approx(0.41)
    assert window.max_pause == pytest.approx(0.4)
    assert [(p.generation, p.collected) for p in slow] == [(2, 1234)]
    assert slow[0].duration == pytest.approx(0.4)
    assert tracker.drain_slow_pauses() == []


def test_gc_tracker_window_only_holds_collections_since_the_last_take() -> None:
    clock = ManualClock()
    tracker = GcPauseTracker(clock=clock, slow_threshold=0.25)
    _collect(tracker, clock, 2, 0.5)
    tracker.take_window()
    _collect(tracker, clock, 0, 0.1)

    window = tracker.take_window()

    assert window.counts == {0: 1}
    assert window.max_pause == pytest.approx(0.1)


def test_gc_tracker_ignores_stop_without_start() -> None:
    # Installed mid-collection: the first callback it sees is a "stop".
    tracker = GcPauseTracker(clock=ManualClock(), slow_threshold=0.25)
    tracker("stop", {"generation": 1, "collected": 0, "uncollectable": 0})

    assert tracker.take_window().counts == {}


def test_gc_tracker_sees_real_collections() -> None:
    tracker = GcPauseTracker()
    gc.callbacks.append(tracker)
    try:
        gc.collect()
    finally:
        gc.callbacks.remove(tracker)

    assert tracker.take_window().counts.get(2, 0) >= 1


async def test_monitor_logs_loop_lag(caplog: pytest.LogCaptureFixture) -> None:
    monitor = EventLoopMonitor(probe_interval=0.05, summary_interval=3600, slow_threshold=0.2)
    task = asyncio.create_task(monitor.run())
    with caplog.at_level(logging.INFO, logger="speedfog_racing.services.loop_monitor"):
        await asyncio.sleep(0.1)
        time.sleep(0.3)  # a coroutine computing without awaiting
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    lags = [
        (r.levelno, int(m.group(1)), int(m.group(2)))
        for r in caplog.records
        if (m := LAG_LINE.match(r.getMessage()))
    ]
    # The freeze is not a collection: the lag line must not blame the GC.
    assert any(
        level == logging.WARNING and ms >= 250 and gc_ms < 50 for level, ms, gc_ms in lags
    ), lags


async def test_monitor_lag_line_carries_the_gc_time_of_the_wait(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = ManualClock()
    tracker = GcPauseTracker(clock=clock)
    monitor = EventLoopMonitor(
        probe_interval=0.05, summary_interval=3600, slow_threshold=0.2, gc_tracker=tracker
    )
    gc.disable()  # only the simulated collection below
    try:
        task = asyncio.create_task(monitor.run())
        with caplog.at_level(logging.INFO, logger="speedfog_racing.services.loop_monitor"):
            await asyncio.sleep(0.1)
            _collect(tracker, clock, 2, 0.4)
            time.sleep(0.4)  # the loop frozen while that collection ran
            await asyncio.sleep(0.1)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    finally:
        gc.enable()

    lags = [
        (int(m.group(1)), int(m.group(2)))
        for r in caplog.records
        if (m := LAG_LINE.match(r.getMessage()))
    ]
    assert any(ms >= 300 and gc_ms == 400 for ms, gc_ms in lags), lags


async def test_monitor_logs_slow_gc_pause(caplog: pytest.LogCaptureFixture) -> None:
    clock = ManualClock()
    tracker = GcPauseTracker(clock=clock, slow_threshold=0.25)
    _collect(tracker, clock, 2, 0.4, collected=99)
    monitor = EventLoopMonitor(
        probe_interval=0.02, summary_interval=3600, slow_threshold=0.25, gc_tracker=tracker
    )
    task = asyncio.create_task(monitor.run())
    with caplog.at_level(logging.INFO, logger="speedfog_racing.services.loop_monitor"):
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    gc_lines = [r.getMessage() for r in caplog.records if "GC pause" in r.getMessage()]
    assert gc_lines == ["GC pause: generation=2 duration=400 ms collected=99"]


async def test_monitor_summary_covers_the_window(caplog: pytest.LogCaptureFixture) -> None:
    monitor = EventLoopMonitor(probe_interval=0.02, summary_interval=0.15, slow_threshold=0.1)
    task = asyncio.create_task(monitor.run())
    with caplog.at_level(logging.INFO, logger="speedfog_racing.services.loop_monitor"):
        await asyncio.sleep(0.03)
        gc.collect()
        time.sleep(0.12)
        await asyncio.sleep(0.25)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    summaries = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Event loop:")]
    counts = [re.search(r"gen2=(\d+) .* slow=(\d+)", s) for s in summaries]
    assert counts and all(counts), summaries
    # A slow runner can split the run over several windows: sum them.
    assert sum(int(m.group(1)) for m in counts if m) >= 1  # the explicit gc.collect()
    assert sum(int(m.group(2)) for m in counts if m) >= 1  # the blocking sleep


async def test_monitor_uninstalls_its_gc_callback_on_cancel() -> None:
    monitor = EventLoopMonitor(probe_interval=0.02, summary_interval=3600)
    callbacks_before = list(gc.callbacks)
    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.05)
    assert len(gc.callbacks) == len(callbacks_before) + 1
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert gc.callbacks == callbacks_before


def test_app_lifespan_runs_the_monitor() -> None:
    """The app starts the monitor with the server and removes its hook at shutdown."""
    from fastapi.testclient import TestClient

    from speedfog_racing.main import app

    with TestClient(app):
        assert any(isinstance(cb, GcPauseTracker) for cb in gc.callbacks)

    assert not any(isinstance(cb, GcPauseTracker) for cb in gc.callbacks)
