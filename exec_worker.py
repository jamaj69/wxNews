#!/usr/bin/env python3
"""
exec_worker.py — Generic async task executor with three dispatch backends.

Dispatches tasks to the appropriate pool based on task kind:

  TaskKind.CPU    → ProcessPoolExecutor  (true parallelism, GIL-free)
                    ``fn`` must be a dotted import path: ``"module.function"``.
                    All args / kwargs / return values must be **picklable**.

  TaskKind.THREAD → ThreadPoolExecutor   (blocking I/O in threads)
                    ``fn`` is a regular callable in the current process.
                    Suitable for sync HTTP clients, file I/O, etc.

  TaskKind.ASYNC  → asyncio event loop   (non-blocking async I/O)
                    ``fn`` is an ``async def`` coroutine function.
                    Suitable for aiohttp, aiosqlite, etc.

All task inputs and outputs are plain dicts / dataclasses — JSON-friendly
and safe to pass through ``asyncio.Queue`` instances.

Quick start
───────────
    pool = ExecWorkerPool(cpu_workers=32, thread_workers=16)
    pool.start()

    # CPU task: fn is a dotted import path
    r = await pool.submit(Task(
        kind=TaskKind.CPU,
        fn="text_utils.sanitize_html_content",
        args=(raw_html,),
    ))

    # Thread task: fn is a callable
    r = await pool.submit(Task(
        kind=TaskKind.THREAD,
        fn=requests.get,
        args=(url,),
        kwargs={"timeout": 10},
    ))

    # Async task: fn is a coroutine function
    r = await pool.submit(Task(
        kind=TaskKind.ASYNC,
        fn=session.get,
        args=(url,),
    ))

    pool.stop()

Queue-pipeline integration
──────────────────────────
Items fed into ``in_q`` can be ``Task`` instances or plain dicts.
Results come out of ``out_q`` as ``TaskResult.to_dict()`` plain dicts.

    asyncio.create_task(pool.run_queue(in_q, out_q))

Integration with pipeline.py
─────────────────────────────
``ExecWorkerPool`` is the execution backend; ``PipelineStage`` / ``PipelineSupervisor``
(pipeline.py) handle queue routing, worker scaling, and lifecycle.
A ``PipelineStage`` handler calls ``pool.submit()`` for each item.

    async def my_stage_handler(pool, item):
        result = await pool.submit(Task(
            kind=TaskKind.CPU,
            fn="mymodule.heavy_function",
            args=(item,),
        ))
        if result.ok:
            return result.result
        raise RuntimeError(result.error)
"""
from __future__ import annotations

import asyncio
import functools
import importlib
import os
import time
import traceback
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


# ─── Task kinds ──────────────────────────────────────────────────────────────

class TaskKind(str, Enum):
    CPU    = "cpu"     # ProcessPoolExecutor — subprocess, true parallelism
    THREAD = "thread"  # ThreadPoolExecutor  — thread, blocking I/O
    ASYNC  = "async"   # coroutine           — async I/O in event loop


# ─── Wire types (fully picklable / JSON-friendly) ────────────────────────────

@dataclass
class Task:
    """
    Describes a unit of work to dispatch.

    Picklability rules
    ------------------
    CPU    : ``fn`` must be a dotted module path string, e.g. ``"pkg.mod.func"``.
             ``args`` and ``kwargs`` must be picklable (no lambdas, file handles, …).
             The function must be importable inside every subprocess worker.

    THREAD : ``fn`` is a regular callable in the current process.
             Not sent to another process — picklability is not required.

    ASYNC  : ``fn`` is a coroutine function (``async def``).
             Runs in the current event loop — no serialisation at all.
    """
    kind:    TaskKind
    fn:      str | Callable           # str for CPU; callable for THREAD/ASYNC
    args:    tuple = field(default_factory=tuple)
    kwargs:  dict  = field(default_factory=dict)
    task_id: str   = field(default_factory=lambda: str(uuid.uuid4()))
    meta:    dict  = field(default_factory=dict)   # opaque, pass-through to result

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        """Reconstruct a Task from a plain dict (e.g. received from a queue)."""
        return cls(
            kind    = TaskKind(d["kind"]),
            fn      = d["fn"],
            args    = tuple(d.get("args", ())),
            kwargs  = dict(d.get("kwargs", {})),
            task_id = d.get("task_id", str(uuid.uuid4())),
            meta    = dict(d.get("meta", {})),
        )

    def to_dict(self) -> dict:
        fn_repr = (
            self.fn if isinstance(self.fn, str)
            else getattr(self.fn, "__qualname__", repr(self.fn))
        )
        return {
            "kind":    self.kind.value,
            "fn":      fn_repr,
            "args":    list(self.args),
            "kwargs":  self.kwargs,
            "task_id": self.task_id,
            "meta":    self.meta,
        }


@dataclass
class TaskResult:
    """Result returned by ``ExecWorkerPool.submit()``."""
    task_id:    str
    result:     Any           = None
    error:      Optional[str] = None   # full traceback string on failure
    elapsed_ms: float         = 0.0
    meta:       dict          = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "task_id":    self.task_id,
            "ok":         self.ok,
            "result":     self.result,
            "error":      self.error,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "meta":       self.meta,
        }


# ─── CPU dispatch — top-level so subprocess can pickle it ────────────────────

def _cpu_dispatch(fn_path: str, args: tuple, kwargs: dict) -> Any:
    """
    Runs inside a subprocess worker.  Resolves ``fn_path`` via importlib and
    calls the function with ``args`` / ``kwargs``.  Must remain a module-level
    function so that ``ProcessPoolExecutor`` can pickle it.

    ``fn_path`` format: ``"package.module.function_name"``
    """
    if "." not in fn_path:
        raise ImportError(
            f"fn_path must be 'module.function', got {fn_path!r}. "
            "Top-level builtins are not supported."
        )
    mod_path, fn_name = fn_path.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    fn  = getattr(mod, fn_name)
    return fn(*args, **kwargs)


# ─── Stats ───────────────────────────────────────────────────────────────────

@dataclass
class _KindStats:
    submitted:  int   = 0
    completed:  int   = 0
    errors:     int   = 0
    total_ms:   float = 0.0

    @property
    def avg_ms(self) -> float:
        return round(self.total_ms / self.completed, 1) if self.completed else 0.0

    def to_dict(self) -> dict:
        return {
            "submitted": self.submitted,
            "completed": self.completed,
            "errors":    self.errors,
            "avg_ms":    self.avg_ms,
        }


# ─── Pool ────────────────────────────────────────────────────────────────────

class ExecWorkerPool:
    """
    Async-friendly multi-backend task dispatcher.

    Parameters
    ──────────
    cpu_workers    : size of the ``ProcessPoolExecutor``
                     Default: ``os.cpu_count()``  (e.g. 80 on your system)
    thread_workers : size of the ``ThreadPoolExecutor``
                     Default: ``min(32, cpu_count * 4)``

    All errors are captured in ``TaskResult.error`` — ``submit()`` never raises
    (unless the pool was not started).
    """

    def __init__(
        self,
        cpu_workers:    int | None = None,
        thread_workers: int | None = None,
    ) -> None:
        n = os.cpu_count() or 4
        self._n_cpu    = cpu_workers    if cpu_workers    is not None else n
        self._n_thread = thread_workers if thread_workers is not None else min(32, n * 4)
        self._proc_pool:   Optional[ProcessPoolExecutor] = None
        self._thread_pool: Optional[ThreadPoolExecutor]  = None
        self._stats: dict[TaskKind, _KindStats] = {k: _KindStats() for k in TaskKind}
        self._started = False

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> "ExecWorkerPool":
        """Create executor pools.  Returns ``self`` for chaining."""
        if self._started:
            return self
        self._proc_pool   = ProcessPoolExecutor(max_workers=self._n_cpu)
        self._thread_pool = ThreadPoolExecutor(max_workers=self._n_thread)
        self._started = True
        return self

    def stop(self, wait: bool = True) -> None:
        """Shut down both executor pools, optionally waiting for pending tasks."""
        if self._proc_pool:
            self._proc_pool.shutdown(wait=wait)
            self._proc_pool = None
        if self._thread_pool:
            self._thread_pool.shutdown(wait=wait)
            self._thread_pool = None
        self._started = False

    # sync context manager
    def __enter__(self) -> "ExecWorkerPool":
        return self.start()

    def __exit__(self, *_: Any) -> None:
        self.stop()

    # ── single dispatch ───────────────────────────────────────────────────────

    async def submit(self, task: Task) -> TaskResult:
        """
        Dispatch a single task to the appropriate backend and await the result.

        CPU    tasks run in a subprocess (``ProcessPoolExecutor``).
        THREAD tasks run in a thread     (``ThreadPoolExecutor``).
        ASYNC  tasks run directly in the current event loop.

        Never raises — all errors are wrapped in ``TaskResult.error``.
        """
        if not self._started:
            raise RuntimeError("ExecWorkerPool not started — call start() first")

        loop = asyncio.get_event_loop()
        st   = self._stats[task.kind]
        st.submitted += 1
        t0 = time.monotonic()

        try:
            if task.kind is TaskKind.CPU:
                if not isinstance(task.fn, str):
                    raise TypeError(
                        f"CPU tasks require fn as a dotted import path string, "
                        f"got {type(task.fn).__name__!r}"
                    )
                result = await loop.run_in_executor(
                    self._proc_pool,
                    _cpu_dispatch,
                    task.fn,
                    task.args,
                    task.kwargs,
                )

            elif task.kind is TaskKind.THREAD:
                result = await loop.run_in_executor(
                    self._thread_pool,
                    functools.partial(task.fn, *task.args, **task.kwargs),
                )

            elif task.kind is TaskKind.ASYNC:
                result = await task.fn(*task.args, **task.kwargs)

            else:
                raise ValueError(f"Unknown TaskKind: {task.kind!r}")

            elapsed = (time.monotonic() - t0) * 1000
            st.completed += 1
            st.total_ms  += elapsed
            return TaskResult(
                task_id=task.task_id,
                result=result,
                elapsed_ms=elapsed,
                meta=task.meta,
            )

        except Exception:
            elapsed = (time.monotonic() - t0) * 1000
            st.errors   += 1
            st.total_ms += elapsed
            return TaskResult(
                task_id=task.task_id,
                error=traceback.format_exc(),
                elapsed_ms=elapsed,
                meta=task.meta,
            )

    # ── batch dispatch ────────────────────────────────────────────────────────

    async def map(self, tasks: list[Task]) -> list[TaskResult]:
        """
        Submit all tasks concurrently and return results in submission order.

        All tasks are started before any result is awaited, maximising
        overlap across CPU workers, threads, and async I/O.
        """
        return list(await asyncio.gather(*(self.submit(t) for t in tasks)))

    # ── queue bridge (pipeline integration) ──────────────────────────────────

    async def run_queue(
        self,
        in_q:  asyncio.Queue,
        out_q: asyncio.Queue,
        *,
        sentinel: Any = None,
    ) -> None:
        """
        Background consumer — connects two ``asyncio.Queue`` instances.

        Reads items from ``in_q``, dispatches them, writes ``TaskResult``
        dicts to ``out_q``.  Exits cleanly when ``sentinel`` is received
        (sentinel is forwarded to ``out_q`` for downstream stages).

        Items in ``in_q`` may be:
            • ``Task`` instances
            • plain dicts  (reconstructed via ``Task.from_dict``)
            • the sentinel value

        Items put into ``out_q`` are always ``TaskResult.to_dict()`` dicts,
        except the sentinel which is forwarded as-is.

        Typical use with pipeline.py
        ─────────────────────────────
        Run multiple ``run_queue`` coroutines concurrently to saturate the
        pool (each handles one item at a time; the pool itself is parallel):

            workers = [
                asyncio.create_task(pool.run_queue(in_q, out_q))
                for _ in range(concurrency)
            ]
            await asyncio.gather(*workers)
        """
        while True:
            item = await in_q.get()
            try:
                if item is sentinel:
                    await out_q.put(sentinel)
                    return
                task   = item if isinstance(item, Task) else Task.from_dict(item)
                result = await self.submit(task)
                await out_q.put(result.to_dict())
            finally:
                in_q.task_done()

    # ── introspection ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a JSON-serialisable snapshot of pool config and stats."""
        return {
            "cpu_workers":    self._n_cpu,
            "thread_workers": self._n_thread,
            "started":        self._started,
            "stats":          {k.value: v.to_dict() for k, v in self._stats.items()},
        }

    def __repr__(self) -> str:
        state = "started" if self._started else "stopped"
        return (
            f"ExecWorkerPool({state}, "
            f"cpu={self._n_cpu}, thread={self._n_thread})"
        )
