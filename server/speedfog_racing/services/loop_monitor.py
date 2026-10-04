"""Event-loop health monitor: garbage-collection pauses and loop lag.

The server runs on a single asyncio event loop, so anything that holds it (a
coroutine computing without awaiting, a full garbage collection over a large
heap) freezes every connection and request at once. Sampling profilers charge
a collection to the bytecode right after the allocating call that crossed the
collection threshold, which hides it. This monitor measures both directly:

- every collection is timed through ``gc.callbacks``; a pause at or above
  ``SLOW_THRESHOLD`` is logged on its own (WARNING);
- a probe sleeps ``PROBE_INTERVAL`` and measures how late it wakes up; a lag
  at or above ``SLOW_THRESHOLD`` is logged on its own (WARNING), with the GC
  time spent during that wait;
- every ``SUMMARY_INTERVAL`` an INFO line sums up the window: collections per
  generation, total and longest GC pause, longest lag, slow probes, and the
  process RSS.

The GC callback only records numbers: logging from inside a collection could
re-enter logging handlers, so the probe logs the slow pauses when it wakes up.

``tuned_gc`` adjusts the collector itself for the server's lifetime.
"""

import asyncio
import gc
import logging
import mmap
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PROBE_INTERVAL = 0.1  # seconds
SUMMARY_INTERVAL = 60.0  # seconds
SLOW_THRESHOLD = 0.25  # seconds


@contextmanager
def tuned_gc(gen0_threshold: int) -> Iterator[None]:
    """Tune the collector for the server's lifetime, then restore it.

    ``gen0_threshold`` is the number of net allocations of GC-tracked objects
    between two young collections (0 leaves the collector alone). Objects
    alive at a young collection are promoted; a full collection is considered
    every 11 middle collections and runs once the objects promoted since the
    last one reach 25% of the old generation. A larger threshold lets
    short-lived objects die unseen and makes full collections rarer, at the
    cost of longer young collections and of cyclic garbage living longer.

    What startup allocated (modules, routes, models, translations) lives as
    long as the process: it is frozen, so full collections stop walking it
    (a frozen object that later becomes cyclic garbage is only reclaimed after
    the exit). Not re-entrant: the exit unfreezes everything.
    """
    if gen0_threshold <= 0:
        yield
        return
    threshold = gc.get_threshold()
    started = time.perf_counter()
    gc.collect()
    gc.freeze()
    gc.set_threshold(gen0_threshold, *threshold[1:])
    logger.info(
        "GC tuned: froze %d objects after a %d ms collection, thresholds %s",
        gc.get_freeze_count(),
        round((time.perf_counter() - started) * 1000),
        gc.get_threshold(),
    )
    try:
        yield
    finally:
        gc.set_threshold(*threshold)
        gc.unfreeze()


@dataclass(frozen=True)
class GcPause:
    generation: int
    duration: float
    collected: int


@dataclass
class GcWindow:
    """Collections seen since the window started, keyed by generation."""

    counts: dict[int, int] = field(default_factory=dict)
    total: float = 0.0
    max_pause: float = 0.0


class GcPauseTracker:
    """``gc.callbacks`` hook that times every collection.

    Assumes the GIL build: collections never overlap, and the start and stop
    callbacks of one collection run on the thread that triggered it.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.perf_counter,
        slow_threshold: float = SLOW_THRESHOLD,
    ) -> None:
        self._clock = clock
        self._slow_threshold = slow_threshold
        self._started: float | None = None
        self._window = GcWindow()
        self._slow: list[GcPause] = []
        # Never reset: callers diff two readings to get the GC time in between.
        self.cumulative = 0.0

    def __call__(self, phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            self._started = self._clock()
            return
        if self._started is None:
            # Installed while a collection was running: nothing to time.
            return
        duration = self._clock() - self._started
        self._started = None
        generation = info["generation"]
        window = self._window
        window.counts[generation] = window.counts.get(generation, 0) + 1
        window.total += duration
        window.max_pause = max(window.max_pause, duration)
        self.cumulative += duration
        if duration >= self._slow_threshold:
            self._slow.append(GcPause(generation, duration, info.get("collected", 0)))

    def take_window(self) -> GcWindow:
        """Return the current window and start a new one."""
        window, self._window = self._window, GcWindow()
        return window

    def drain_slow_pauses(self) -> list[GcPause]:
        """Return the slow pauses recorded since the last drain."""
        slow, self._slow = self._slow, []
        return slow


def _rss_mb() -> int | None:
    """Resident set size of this process, in MB (Linux only)."""
    try:
        with open("/proc/self/statm") as statm:
            pages = int(statm.read().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return pages * mmap.PAGESIZE // (1024 * 1024)


class EventLoopMonitor:
    """Background probe logging GC pauses and event-loop lag (see module doc)."""

    def __init__(
        self,
        *,
        probe_interval: float = PROBE_INTERVAL,
        summary_interval: float = SUMMARY_INTERVAL,
        slow_threshold: float = SLOW_THRESHOLD,
        gc_tracker: GcPauseTracker | None = None,
    ) -> None:
        self._probe_interval = probe_interval
        self._summary_interval = summary_interval
        self._slow_threshold = slow_threshold
        self._gc = gc_tracker or GcPauseTracker(slow_threshold=slow_threshold)
        self._max_lag = 0.0
        self._slow_probes = 0

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        gc.callbacks.append(self._gc)
        try:
            next_summary = loop.time() + self._summary_interval
            while True:
                expected = loop.time() + self._probe_interval
                gc_before = self._gc.cumulative
                await asyncio.sleep(self._probe_interval)
                now = loop.time()
                for pause in self._gc.drain_slow_pauses():
                    logger.warning(
                        "GC pause: generation=%d duration=%d ms collected=%d",
                        pause.generation,
                        round(pause.duration * 1000),
                        pause.collected,
                    )
                self._record_lag(max(0.0, now - expected), self._gc.cumulative - gc_before)
                if now >= next_summary:
                    self._log_summary()
                    next_summary = now + self._summary_interval
        finally:
            gc.callbacks.remove(self._gc)

    def _record_lag(self, lag: float, gc_time: float) -> None:
        self._max_lag = max(self._max_lag, lag)
        if lag >= self._slow_threshold:
            self._slow_probes += 1
            logger.warning(
                "Event loop lag: %d ms (gc %d ms)", round(lag * 1000), round(gc_time * 1000)
            )

    def _log_summary(self) -> None:
        window = self._gc.take_window()
        rss = _rss_mb()
        logger.info(
            "Event loop: gc gen0=%d gen1=%d gen2=%d total=%d ms max=%d ms, "
            "lag max=%d ms slow=%d, rss=%s MB",
            window.counts.get(0, 0),
            window.counts.get(1, 0),
            window.counts.get(2, 0),
            round(window.total * 1000),
            round(window.max_pause * 1000),
            round(self._max_lag * 1000),
            self._slow_probes,
            rss if rss is not None else "?",
        )
        self._max_lag = 0.0
        self._slow_probes = 0
