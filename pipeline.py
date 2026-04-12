"""
pipeline.py — Generic multi-producer / multi-consumer pipeline infrastructure.

Architecture overview
---------------------

                         PipelineSupervisor
                    (monitors depths → scales workers)
                               │
    Producers ──→ PipelineQueue ──→ PipelineStage (N workers, dynamic)
                                            │
                                     PipelineQueue ──→ ... (next stage)

Each PipelineStage manages a pool of asyncio coroutine workers that:
  1. Pull items from *input_queue*
  2. Call ``process_item(item)`` — override in subclass or pass *handler*
  3. Push non-None results to *output_queue*

End-of-stream is signalled in one of two ways:
  a) ``stage.signal_upstream_done()`` — preferred; workers drain the queue
     and exit once it is empty.
  b) Inject a ``None`` sentinel into the queue — workers propagate it through
     to sibling workers so every one eventually exits.

Usage example
-------------

    class MyStage(PipelineStage):
        async def process_item(self, item):
            result = await do_work(item)
            return result   # forwarded downstream; return None to drop

    q_in  = PipelineQueue("input")
    q_out = PipelineQueue("output")
    stage = MyStage("my-stage", q_in, q_out, min_workers=1, max_workers=8)
    sup   = PipelineSupervisor([stage])

    await stage.start(initial=2)
    sup.start()

    # ... producers put items into q_in ...

    stage.signal_upstream_done()
    await stage.wait_done()
    sup.stop()

    # then signal / drain the next stage similarly
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

__all__ = [
    "PipelineQueue",
    "PipelineStage",
    "PipelineSupervisor",
    "StageStats",
]

logger = logging.getLogger(__name__)

# Private sentinel object: returned by PipelineQueue.get_timeout() on timeout.
# Distinct from None so that a real None item (end-of-stream) is still
# distinguishable.
_TIMED_OUT: object = object()


# ---------------------------------------------------------------------------
# StageStats
# ---------------------------------------------------------------------------

@dataclass
class StageStats:
    """
    Per-stage runtime counters.

    All fields are mutated only from within the asyncio event-loop thread,
    so no locking is required.
    """
    processed:  int = 0
    errors:     int = 0
    in_flight:  int = 0
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def to_dict(self) -> dict:
        return {
            "processed": self.processed,
            "errors":    self.errors,
            "in_flight": self.in_flight,
            "elapsed_s": round(self.elapsed_s, 1),
        }


# ---------------------------------------------------------------------------
# PipelineQueue
# ---------------------------------------------------------------------------

class PipelineQueue:
    """
    Thin wrapper around ``asyncio.Queue`` that tracks put/get totals.

    The ``depth`` property (i.e. current queue size) is the primary signal
    used by ``PipelineSupervisor`` to scale worker pools up or down.
    """

    def __init__(self, name: str, maxsize: int = 0) -> None:
        self.name        = name
        self._q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._put_total: int = 0
        self._get_total: int = 0

    # ------------------------------------------------------------------ #
    # Queue operations                                                     #
    # ------------------------------------------------------------------ #

    async def put(self, item: Any) -> None:
        await self._q.put(item)
        self._put_total += 1

    def put_nowait(self, item: Any) -> None:
        self._q.put_nowait(item)
        self._put_total += 1

    async def get(self) -> Any:
        item = await self._q.get()
        self._get_total += 1
        return item

    async def get_timeout(self, timeout: float = 0.5) -> Any:
        """
        Try to get an item within *timeout* seconds.

        Returns the item on success, or the private ``_TIMED_OUT`` sentinel
        on timeout (never raises ``asyncio.TimeoutError``).
        """
        try:
            item = await asyncio.wait_for(self._q.get(), timeout=timeout)
            self._get_total += 1
            return item
        except asyncio.TimeoutError:
            return _TIMED_OUT

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()

    def empty(self) -> bool:
        return self._q.empty()

    # ------------------------------------------------------------------ #
    # Metrics                                                              #
    # ------------------------------------------------------------------ #

    @property
    def depth(self) -> int:
        """Number of items currently waiting in the queue."""
        return self._q.qsize()

    def to_dict(self) -> dict:
        return {
            "name":      self.name,
            "depth":     self.depth,
            "total_put": self._put_total,
            "total_get": self._get_total,
        }


# ---------------------------------------------------------------------------
# PipelineStage
# ---------------------------------------------------------------------------

class PipelineStage:
    """
    One logical stage of a processing pipeline.

    Manages a dynamic pool of asyncio worker coroutines that consume items
    from *input_queue*, transform them via ``process_item()``, and forward
    results to *output_queue*.

    Processing logic
    ~~~~~~~~~~~~~~~~
    Supply via one of:
    * ``handler`` constructor kwarg — ``async def handler(item) -> result | None``
    * Subclass and override ``process_item()``

    Worker lifecycle
    ~~~~~~~~~~~~~~~~
    Workers run in a ``while True`` loop with a short ``get_timeout``.
    They exit when:
    * A ``None`` sentinel is received (propagated to remaining siblings).
    * ``signal_upstream_done()`` was called AND the queue is empty.
    * The worker coroutine is cancelled (supervisor scale-down).
    """

    def __init__(
        self,
        name: str,
        input_queue:  PipelineQueue,
        output_queue: Optional[PipelineQueue] = None,
        *,
        handler:     Optional[Callable[[Any], Awaitable[Optional[Any]]]] = None,
        min_workers: int = 1,
        max_workers: int = 8,
    ) -> None:
        self.name         = name
        self.input_queue  = input_queue
        self.output_queue = output_queue
        self.min_workers  = min_workers
        self.max_workers  = max_workers
        self.stats        = StageStats()

        self._handler               = handler
        self._workers: dict[int, asyncio.Task] = {}
        self._next_id               = 0
        self._upstream_done         = asyncio.Event()  # no more items arriving
        self._all_done              = asyncio.Event()  # all workers exited
        self._log = logging.getLogger(f"pipeline.{name}")

    # ------------------------------------------------------------------ #
    # Override point                                                       #
    # ------------------------------------------------------------------ #

    async def process_item(self, item: Any) -> Optional[Any]:
        """
        Process one item from *input_queue*.

        Return the result to forward to *output_queue*, or ``None`` to discard.
        Must be overridden unless a *handler* was supplied to the constructor.
        """
        if self._handler is not None:
            return await self._handler(item)
        raise NotImplementedError(
            f"{self.__class__.__name__}.process_item() is not implemented "
            "and no handler was provided."
        )

    # ------------------------------------------------------------------ #
    # Internal worker coroutine                                           #
    # ------------------------------------------------------------------ #

    async def _worker(self, wid: int) -> None:
        self._log.debug("Worker %d started (pool=%d)", wid, len(self._workers))
        try:
            while True:
                item = await self.input_queue.get_timeout(timeout=0.3)

                # ---- Timeout: check whether we should exit ----
                if item is _TIMED_OUT:
                    if self._upstream_done.is_set() and self.input_queue.empty():
                        break
                    continue

                # ---- None sentinel: upstream is exhausted ----
                if item is None:
                    self._upstream_done.set()
                    # Propagate to remaining sibling workers so they all exit
                    remaining = len(self._workers) - 1
                    if remaining > 0:
                        await self.input_queue.put(None)
                    self.input_queue.task_done()
                    break

                # ---- Real item: process it ----
                self.stats.in_flight += 1
                try:
                    result = await self.process_item(item)
                    self.stats.processed += 1
                    if result is not None and self.output_queue is not None:
                        await self.output_queue.put(result)
                except Exception as exc:
                    self.stats.errors += 1
                    self._log.error(
                        "Worker %d error processing item: %s", wid, exc,
                        exc_info=True,
                    )
                finally:
                    self.stats.in_flight -= 1
                    self.input_queue.task_done()

        except asyncio.CancelledError:
            self._log.debug("Worker %d cancelled", wid)
            raise
        finally:
            self._workers.pop(wid, None)
            remaining = len(self._workers)
            self._log.debug("Worker %d exited (remaining=%d)", wid, remaining)
            if remaining == 0:
                self._all_done.set()

    # ------------------------------------------------------------------ #
    # Public lifecycle API                                                #
    # ------------------------------------------------------------------ #

    async def start(self, initial: int = 1) -> None:
        """
        Spawn *initial* workers (clamped to ``[min_workers, max_workers]``).

        Safe to call when the stage has previously terminated — resets the
        ``_all_done`` event so ``wait_done()`` works correctly.
        """
        self._all_done.clear()
        self._upstream_done.clear()
        n = max(self.min_workers, min(self.max_workers, initial))
        for _ in range(n):
            self._spawn()
        self._log.info("Stage '%s' started — %d worker(s)", self.name, n)

    def signal_upstream_done(self) -> None:
        """
        Declare that the upstream producer has finished; no more items will
        be added to *input_queue*.  Workers will drain remaining items then
        exit cleanly.
        """
        self._upstream_done.set()
        self._log.debug("Stage '%s' upstream marked done", self.name)

    async def wait_done(self) -> None:
        """Block until all workers have exited."""
        if not self._workers:
            self._all_done.set()
            return
        await self._all_done.wait()

    def scale_to(self, target: int) -> None:
        """
        Adjust the live worker count toward *target*
        (clamped to ``[min_workers, max_workers]``).

        Ignored once ``signal_upstream_done()`` has been called.
        """
        if self._upstream_done.is_set():
            return
        target  = max(self.min_workers, min(self.max_workers, target))
        current = self.worker_count
        if target > current:
            for _ in range(target - current):
                self._spawn()
            self._log.info("Scaled UP '%s': %d → %d", self.name, current, target)
        elif target < current:
            for _ in range(current - target):
                self._cancel_one()
            self._log.info("Scaled DOWN '%s': %d → %d", self.name, current, target)

    @property
    def worker_count(self) -> int:
        """Current number of live worker coroutines."""
        return len(self._workers)

    def to_dict(self) -> dict:
        return {
            "stage":       self.name,
            "workers":     self.worker_count,
            "min_workers": self.min_workers,
            "max_workers": self.max_workers,
            "queue_depth": self.input_queue.depth,
            **self.stats.to_dict(),
        }

    # ------------------------------------------------------------------ #
    # Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _spawn(self) -> int:
        wid  = self._next_id
        self._next_id += 1
        task = asyncio.create_task(
            self._worker(wid), name=f"{self.name}-w{wid}"
        )
        self._workers[wid] = task
        return wid

    def _cancel_one(self) -> None:
        """Cancel the most-recently-spawned idle worker (scale-down)."""
        if self._workers:
            wid, task = next(reversed(self._workers.items()))
            task.cancel()


# ---------------------------------------------------------------------------
# PipelineSupervisor
# ---------------------------------------------------------------------------

class PipelineSupervisor:
    """
    Periodically inspects each supervised ``PipelineStage``'s input-queue
    depth and adjusts the worker-pool size accordingly:

    * ``depth > scale_up_threshold``  → add workers (up to ``max_workers``)
    * ``depth < scale_down_threshold`` AND ``workers > min_workers``
                                      → remove one worker

    Stops supervising a stage once its upstream is marked done (no point
    spawning new workers when there are no more items to process).

    The supervisor runs as a background asyncio task and does not block
    the event loop.
    """

    def __init__(
        self,
        stages: list[PipelineStage],
        *,
        check_interval:        float = 2.0,
        scale_up_threshold:    int   = 10,
        scale_down_threshold:  int   = 2,
    ) -> None:
        self.stages               = stages
        self.check_interval       = check_interval
        self.scale_up_threshold   = scale_up_threshold
        self.scale_down_threshold = scale_down_threshold
        self._stop                = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._log  = logging.getLogger("pipeline.supervisor")

    # ------------------------------------------------------------------ #
    # Internal loop                                                        #
    # ------------------------------------------------------------------ #

    async def _loop(self) -> None:
        while not self._stop.is_set():
            for stage in self.stages:
                # Don't touch stages that are already draining
                if stage._upstream_done.is_set():
                    continue
                depth   = stage.input_queue.depth
                current = stage.worker_count

                if depth > self.scale_up_threshold and current < stage.max_workers:
                    divisor = self.scale_up_threshold or 1
                    new = min(
                        stage.max_workers,
                        current + max(1, depth // divisor),
                    )
                    stage.scale_to(new)
                elif depth < self.scale_down_threshold and current > stage.min_workers:
                    stage.scale_to(current - 1)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.check_interval)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def start(self) -> asyncio.Task:
        """Start the supervisor as a background asyncio task."""
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="pipeline-supervisor")
        self._log.debug(
            "Supervisor started — %d stage(s), interval=%.1fs",
            len(self.stages), self.check_interval,
        )
        return self._task

    def stop(self) -> None:
        """Stop the supervisor loop."""
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()

    def status(self) -> dict:
        """Return a serialisable snapshot of supervisor + stage state."""
        return {
            "running": self._task is not None and not self._task.done(),
            "stages":  [s.to_dict() for s in self.stages],
        }
