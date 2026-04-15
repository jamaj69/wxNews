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

    def stats(self, since_ts: Optional[float] = None) -> Dict[str, Dict]:
        """
        Aggregate per-function stats from the ring buffer.
        If since_ts is given (time.time() value), only spans with
        wall_time >= since_ts are included.
        Returned dict is sorted by max_ms descending (worst offenders first).
        """
        by_name: Dict[str, List[float]] = {}
        for r in self._ring:
            if since_ts is not None and r.wall_time < since_ts:
                continue
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


# ---------------------------------------------------------------------------
# Loop lag sensor
# ---------------------------------------------------------------------------

class LoopLagSensor:
    """
    Measures real-time event-loop lag by scheduling ``asyncio.sleep(interval)``
    repeatedly and comparing the actual elapsed time against the expected one.

    A lag >> 0 means the event loop was blocked (e.g. blocking I/O, heavy CPU
    in a coroutine, GIL contention) for the excess duration.

    Usage::

        # start once at service boot
        loop.create_task(lag_sensor.run())

        # query at any time
        lag_sensor.stats()    → dict with avg/max/p95/peak_ever

    The rolling window holds the last ``window`` samples (default 120 × 0.5 s
    = 60 s of history).  ``peak_ever_ms`` survives across rollovers.
    """

    def __init__(self, interval: float = 0.5, window: int = 120) -> None:
        self._interval   = interval
        self._window     = window
        self._samples: deque[float] = deque(maxlen=window)
        self._peak_ms    = 0.0
        self._running    = False

    async def run(self) -> None:
        """Background coroutine — run as an asyncio Task at startup."""
        self._running = True
        loop = asyncio.get_event_loop()
        while True:
            t0 = loop.time()
            await asyncio.sleep(self._interval)
            actual   = loop.time() - t0
            lag_ms   = max(0.0, (actual - self._interval) * 1000.0)
            self._samples.append(lag_ms)
            if lag_ms > self._peak_ms:
                self._peak_ms = lag_ms

    def stats(self, since_ts: Optional[float] = None) -> dict:
        """Return aggregate lag statistics for the current rolling window."""
        samples = list(self._samples)
        if since_ts is not None and samples:
            # Each sample is interval_s apart; most recent is the last element.
            # Estimate how many recent samples fall within the requested window.
            age_s = max(0.0, time.time() - since_ts)
            keep = max(1, round(age_s / self._interval))
            samples = samples[-keep:]
        if not samples:
            return {
                'running': self._running,
                'interval_s': self._interval,
                'window_s': self._window * self._interval,
                'samples': 0,
                'avg_ms': None, 'median_ms': None, 'max_ms': None,
                'p95_ms': None, 'peak_ever_ms': round(self._peak_ms, 2),
            }
        s = sorted(samples)
        n = len(s)
        return {
            'running':      self._running,
            'interval_s':   self._interval,
            'window_s':     round(n * self._interval, 1),
            'samples':      n,
            'avg_ms':       round(mean(s), 2),
            'median_ms':    round(median(s), 2),
            'max_ms':       round(max(s), 2),
            'p95_ms':       round(s[int(n * 0.95)], 2) if n >= 20 else None,
            'peak_ever_ms': round(self._peak_ms, 2),
        }

    def reset_peak(self) -> None:
        """Reset the all-time peak (e.g. after a known startup spike)."""
        self._peak_ms = 0.0


# Global singleton
lag_sensor = LoopLagSensor(interval=0.5, window=120)


# ---------------------------------------------------------------------------
# Stall probe — reusable for any worker type
# ---------------------------------------------------------------------------

class StallProbe:
    """
    Rate-limited stall detector for workers (sync or async).

    Tracks elapsed time since the last "success" event and emits a WARNING
    log when a configurable threshold is exceeded **and** there is pending
    work to be done.  Warnings back off exponentially (threshold doubles on
    each trigger) so log spam is avoided during prolonged stalls.  The
    threshold resets every time :meth:`reset` is called (i.e. on each
    successful response).

    The log message format is standardised so that ``grep``/``journalctl``
    queries work uniformly across all worker types::

        WARNING mypackage.translatev1 MyWorker.pump: no response for 60s,
                pending=8, subprocess_alive=True, exitcode=None

    Sync usage (pump threads / blocking consumer loops)::

        probe = StallProbe("NLLBWorker.pump", logger, warn_after=60.0)
        while running:
            try:
                item = q.get(timeout=0.5)
            except queue.Empty:
                probe.check(pending=len(pending), subprocess_alive=proc.is_alive())
                continue
            probe.reset()
            # process item …

    Async usage (asyncio workers / monitoring tasks)::

        probe = StallProbe("EnrichmentWorker", logger, warn_after=60.0)
        while True:
            item = await q.get()
            probe.reset()
            # process item …

        # In a periodic monitor coroutine:
        await probe.check_async(pending=input_q.qsize())
    """

    def __init__(
        self,
        name:       str,
        logger:     "logging.Logger",
        warn_after: float = 60.0,
    ) -> None:
        import logging as _logging
        self._name       = name
        self._log        = logger
        self._warn_after = warn_after          # initial threshold (s)
        self._threshold  = warn_after          # current threshold (doubles on each hit)
        self._last_ok    = time.monotonic()    # time of last successful event

    # ------------------------------------------------------------------
    # Core events
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Call on every successful event (response received, item processed)."""
        self._last_ok   = time.monotonic()
        self._threshold = self._warn_after     # reset exponential back-off

    def elapsed(self) -> float:
        """Seconds since the last successful event."""
        return time.monotonic() - self._last_ok

    # ------------------------------------------------------------------
    # Sync check (call from a thread / blocking loop on each idle tick)
    # ------------------------------------------------------------------

    def check(self, pending: int, **state) -> bool:
        """
        Emit a stall WARNING if elapsed >= threshold and *pending* > 0.

        Extra keyword arguments are appended to the log message verbatim,
        e.g. ``subprocess_alive=True, exitcode=None``.

        Returns ``True`` if a warning was emitted, ``False`` otherwise.
        """
        if pending <= 0:
            return False
        elapsed = self.elapsed()
        if elapsed < self._threshold:
            return False
        extras = ", ".join(f"{k}={v}" for k, v in state.items())
        self._log.warning(
            "%s: no response for %.0fs, pending=%d%s",
            self._name, elapsed, pending,
            (", " + extras) if extras else "",
        )
        self._threshold *= 2   # back off — next warning at 2× the current interval
        return True

    # ------------------------------------------------------------------
    # Async check (call from a monitoring coroutine / periodic task)
    # ------------------------------------------------------------------

    async def check_async(self, pending: int, **state) -> bool:
        """Async-compatible wrapper — same behaviour as :meth:`check`."""
        return self.check(pending, **state)
