"""
loop_watchdog.py — Async event-loop span profiler.

Records call spans (name, start_ts, end_ts, duration_ms, task_name) in a
fixed-size circular ring buffer (deque maxlen=1000).  Thread-safe via GIL
(deque.append is atomic in CPython).

Usage — context manager (recommended):
    from loop_watchdog import watchdog

    async def my_func():
        async with watchdog.span("my_func"):
            ...

Usage — decorator:
    @watchdog.track
    async def my_func():
        ...

Query:
    watchdog.get_recent(n=50)            → last N spans, newest first
    watchdog.get_slow(threshold_ms=50)   → spans >= threshold, newest first
    watchdog.stats()                     → per-function aggregate stats dict
    watchdog.clear()                     → empty the ring buffer
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import time
from collections import deque
from dataclasses import dataclass
from statistics import mean, median
from typing import AsyncIterator, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data record
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SpanRecord:
    """One recorded function span."""
    name:        str    # function / stage label
    start_ts:    float  # time.monotonic() at entry
    end_ts:      float  # time.monotonic() at exit
    duration_ms: float  # (end_ts - start_ts) * 1000
    task_name:   str    # asyncio.Task name — empty for synchronous callers
    wall_time:   float  # time.time() at exit (for human-readable timestamps)


# ---------------------------------------------------------------------------
# Watchdog class
# ---------------------------------------------------------------------------

class LoopWatchdog:
    """Fixed-size circular ring buffer of async span records."""

    def __init__(self, maxlen: int = 1000) -> None:
        self._ring: deque[SpanRecord] = deque(maxlen=maxlen)
        self._maxlen = maxlen

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, name: str, start_ts: float, end_ts: float,
               task_name: str = '') -> None:
        """
        Record a completed span.  Can be called from async or sync context.
        GIL makes deque.append() effectively atomic — no locking needed.
        """
        self._ring.append(SpanRecord(
            name=name,
            start_ts=start_ts,
            end_ts=end_ts,
            duration_ms=(end_ts - start_ts) * 1000.0,
            task_name=task_name,
            wall_time=time.time(),
        ))

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def span(self, name: str) -> AsyncIterator[None]:
        """
        Async context manager — captures start timestamp on entry,
        records the span (always, even on exception) on exit.

            async with watchdog.span("my_stage"):
                ...
        """
        task = asyncio.current_task()
        task_name = task.get_name() if task else ''
        t0 = time.monotonic()
        try:
            yield
        finally:
            self.record(name, t0, time.monotonic(), task_name)

    # ------------------------------------------------------------------
    # Decorator
    # ------------------------------------------------------------------

    def track(self, func: Callable) -> Callable:
        """
        Async function decorator.  Uses the qualified name of the function
        as the span label.

            @watchdog.track
            async def fetch_rss(...):
                ...
        """
        label = func.__qualname__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            async with self.span(label):
                return await func(*args, **kwargs)

        return wrapper

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_recent(self, n: int = 100, min_ms: float = 0.0) -> List[Dict]:
        """
        Return the *n* most recent spans (newest first) as plain dicts.
        Optionally filter by min duration (``min_ms``).
        """
        records = list(self._ring)
        records.reverse()
        if min_ms > 0:
            records = [r for r in records if r.duration_ms >= min_ms]
        return [
            {
                'name':        r.name,
                'duration_ms': round(r.duration_ms, 2),
                'task_name':   r.task_name,
                'wall_time':   r.wall_time,
                'start_ts':    round(r.start_ts, 6),
                'end_ts':      round(r.end_ts, 6),
            }
            for r in records[:n]
        ]

    def get_slow(self, threshold_ms: float = 50.0) -> List[Dict]:
        """
        Return ALL spans slower than *threshold_ms*, newest first.
        Useful for quickly spotting who is blocking the loop.
        """
        records = [r for r in self._ring if r.duration_ms >= threshold_ms]
        records.sort(key=lambda r: r.start_ts, reverse=True)
        return [
            {
                'name':        r.name,
                'duration_ms': round(r.duration_ms, 2),
                'task_name':   r.task_name,
                'wall_time':   r.wall_time,
            }
            for r in records
        ]

    def stats(self) -> Dict[str, Dict]:
        """
        Aggregate per-function stats from the entire ring buffer contents.
        Returned dict is sorted by max_ms descending (worst offenders first).
        """
        by_name: Dict[str, List[float]] = {}
        for r in self._ring:
            by_name.setdefault(r.name, []).append(r.duration_ms)

        result: Dict[str, Dict] = {}
        for name, durations in by_name.items():
            result[name] = {
                'count':       len(durations),
                'avg_ms':      round(mean(durations), 2),
                'median_ms':   round(median(durations), 2),
                'max_ms':      round(max(durations), 2),
                'min_ms':      round(min(durations), 2),
                'p95_ms':      round(sorted(durations)[int(len(durations) * 0.95)], 2)
                               if len(durations) >= 20 else None,
                'slow_count':  sum(1 for d in durations if d >= 50.0),
            }
        return dict(sorted(result.items(), key=lambda x: x[1]['max_ms'], reverse=True))

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Empty the ring buffer."""
        self._ring.clear()

    def __len__(self) -> int:
        return len(self._ring)

    @property
    def maxlen(self) -> int:
        return self._maxlen


# ---------------------------------------------------------------------------
# Global singleton — import and use anywhere
# ---------------------------------------------------------------------------

watchdog = LoopWatchdog(maxlen=1000)
