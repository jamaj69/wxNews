#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Translation orchestrator.

Both backends run as persistent subprocesses communicating via queues.
The interface is identical: translate_sync() and translate_async().

Primary backend : Google Translate  (_google — google_worker subprocess)
Fallback backend: NLLB-200 local GPU (_nllb  — nllb_worker   subprocess)
"""

import asyncio
import itertools
import logging
import multiprocessing
import re
import threading
import time as _time
import uuid

import google_worker
import nllb_worker
from lang_rules import AUTO_FALLBACK_TARGET, _load_language_rules, get_language_rules
from text_utils import GOOGLE_MAX_CHARS, MAX_TRANSLATE_CHARS, _strip_html

logger = logging.getLogger(__name__)

# Separator used to batch multiple article fields in a single backend call.
# Chosen to be visually distinct and very unlikely to appear in article text.
_FIELD_SEP = "\n\n<<<SEP>>>\n\n"


# ---------------------------------------------------------------------------
# Common subprocess manager (shared by both backends)
# ---------------------------------------------------------------------------

class _ProcessTranslator:
    """
    Base class for subprocess-based translator backends.

    Subclasses implement only ``_make_process()`` to return the backend-
    specific Process object.  All queue management, pump thread, lifecycle
    (start / shutdown), and the calling interface (translate_sync /
    translate_async) are provided here so both backends are identical.

    Protocol
    --------
    request:  ``(req_id: str, text: str, src_code: str, tgt_code: str)``
            | ``None``  ← shutdown sentinel
    response: ``(req_id: str, translated_str_or_None)``
    """

    _PROCESS_NAME = "translator"
    _PUMP_NAME    = "translator-pump"

    def __init__(self) -> None:
        self._process: multiprocessing.Process | None = None
        self._req_q:   "multiprocessing.Queue[tuple | None]" | None = None
        self._resp_q:  "multiprocessing.Queue[tuple]" | None = None
        self._async_pending: dict[str, "asyncio.Future[str | None]"] = {}
        self._sync_pending:  dict[str, list] = {}
        self._lock         = threading.Lock()
        self._pump_thread: threading.Thread | None = None
        self._loop:        asyncio.AbstractEventLoop | None = None
        self._started      = False
        self._shutdown     = threading.Event()

    def _make_process(
        self,
        ctx: "multiprocessing.context.SpawnContext",
        req_q: "multiprocessing.Queue",
        resp_q: "multiprocessing.Queue",
    ) -> multiprocessing.Process:
        raise NotImplementedError

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Eagerly start the worker subprocess (called at service startup)."""
        self._ensure_started()

    def _ensure_started(self) -> None:
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            ctx = multiprocessing.get_context("spawn")
            self._req_q  = ctx.Queue()
            self._resp_q = ctx.Queue()
            self._process = self._make_process(ctx, self._req_q, self._resp_q)
            self._process.start()
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = None
            self._pump_thread = threading.Thread(
                target=self._pump_responses,
                daemon=True,
                name=self._PUMP_NAME,
            )
            self._pump_thread.start()
            self._started = True
            import atexit
            atexit.register(self.shutdown)

    def _pump_responses(self) -> None:
        """Daemon thread: drains resp_q and wakes waiting callers."""
        from loop_watchdog import StallProbe
        assert self._resp_q is not None
        probe = StallProbe(
            name       = f"{self.__class__.__name__}.pump",
            logger     = logging.getLogger(__name__),
            warn_after = 60.0,
        )
        while not self._shutdown.is_set():
            try:
                item = self._resp_q.get(timeout=0.5)
            except Exception:
                with self._lock:
                    n_pending = len(self._async_pending) + len(self._sync_pending)
                alive    = self._process.is_alive()  if self._process else None
                exitcode = self._process.exitcode    if self._process else None
                probe.check(
                    pending           = n_pending,
                    subprocess_alive  = alive,
                    exitcode          = exitcode,
                )
                continue
            probe.reset()
            req_id, result = item
            with self._lock:
                fut       = self._async_pending.pop(req_id, None)
                sync_slot = self._sync_pending.get(req_id)
            if fut is not None and self._loop is not None:
                self._loop.call_soon_threadsafe(
                    lambda f=fut, r=result: f.set_result(r) if not f.done() else None
                )
            elif sync_slot is not None:
                sync_slot[1] = result
                sync_slot[0].set()

    def shutdown(self) -> None:
        """Gracefully stop the worker process and resolve all pending calls."""
        if not self._started or self._shutdown.is_set():
            return
        self._shutdown.set()
        if self._req_q is not None:
            try:
                self._req_q.put_nowait(None)   # sentinel → triggers worker exit loop
            except Exception:
                pass
        if self._process is not None:
            self._process.join(timeout=10)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=3)
        if self._pump_thread is not None:
            self._pump_thread.join(timeout=3)
        with self._lock:
            if self._loop is not None:
                for fut in self._async_pending.values():
                    if not fut.done():
                        self._loop.call_soon_threadsafe(fut.set_result, None)
            for slot in self._sync_pending.values():
                slot[0].set()       # unblock threads; result stays None
            self._async_pending.clear()
            self._sync_pending.clear()

    # ── translation interface ─────────────────────────────────────────────────

    def translate_sync(
        self, text: str, src_code: str, tgt_code: str, timeout: float = 120.0
    ) -> str | None:
        """
        Blocking translation for use from any thread (e.g. executor pools).
        Returns the translated string, or None on failure/timeout.
        """
        if self._shutdown.is_set():
            return None
        self._ensure_started()
        req_id = str(uuid.uuid4())
        event  = threading.Event()
        slot: list = [event, None]
        with self._lock:
            self._sync_pending[req_id] = slot
        assert self._req_q is not None
        self._req_q.put((req_id, text, src_code, tgt_code))
        event.wait(timeout=timeout)
        with self._lock:
            self._sync_pending.pop(req_id, None)
        return slot[1]

    # Timeout (seconds) for a single translate_async call.  If the NLLB/Google
    # subprocess does not respond within this window the future is cancelled,
    # the pending entry is removed, and None is returned so the article is
    # queued for a later retry rather than blocking the worker indefinitely.
    ASYNC_TIMEOUT: float = 120.0

    async def translate_async(
        self, text: str, src_code: str, tgt_code: str
    ) -> str | None:
        """
        Non-blocking translation for use inside an asyncio event loop.
        Returns the translated string, or None on failure/timeout.
        """
        if self._shutdown.is_set():
            return None
        self._ensure_started()
        # Restart pump thread if it died unexpectedly.
        if self._pump_thread is not None and not self._pump_thread.is_alive():
            import logging as _logging
            _logging.getLogger(__name__).error(
                "%s pump thread died — restarting", self.__class__.__name__
            )
            self._pump_thread = threading.Thread(
                target=self._pump_responses,
                daemon=True,
                name=self._PUMP_NAME,
            )
            self._pump_thread.start()
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        req_id = str(uuid.uuid4())
        fut: asyncio.Future[str | None] = loop.create_future()
        with self._lock:
            self._async_pending[req_id] = fut
        assert self._req_q is not None
        self._req_q.put((req_id, text, src_code, tgt_code))
        try:
            return await asyncio.wait_for(fut, timeout=self.ASYNC_TIMEOUT)
        except asyncio.TimeoutError:
            import logging as _logging
            alive    = self._process.is_alive()  if self._process else None
            exitcode = self._process.exitcode    if self._process else None
            with self._lock:
                n_pending = len(self._async_pending)
                self._async_pending.pop(req_id, None)
            _logging.getLogger(__name__).warning(
                "%s translate_async timed out after %.0fs "
                "(req_id=%s, subprocess_alive=%s, exitcode=%s, pending=%d)",
                self.__class__.__name__, self.ASYNC_TIMEOUT, req_id,
                alive, exitcode, n_pending,
            )
            return None


# ---------------------------------------------------------------------------
# Backend subclasses — differ only in which subprocess they spawn
# ---------------------------------------------------------------------------

class _GoogleProcessTranslator(_ProcessTranslator):
    """Google Translate backend running as a subprocess."""

    _PROCESS_NAME = "google-translate"
    _PUMP_NAME    = "google-pump"

    def _make_process(self, ctx, req_q, resp_q):
        return ctx.Process(
            target=google_worker.worker,
            args=(req_q, resp_q),
            daemon=True,
            name=self._PROCESS_NAME,
        )


class _NLLBProcessTranslator(_ProcessTranslator):
    """NLLB-200 GPU inference backend running as a subprocess."""

    _PROCESS_NAME = "nllb-gpu"
    _PUMP_NAME    = "nllb-pump"

    def _make_process(self, ctx, req_q, resp_q):
        return ctx.Process(
            target=nllb_worker.worker,
            args=(
                req_q, resp_q,
                nllb_worker.NLLB_MODEL_ID,
                dict(nllb_worker.NLLB_LANG_MAP),
                dict(nllb_worker.NLLB_TARGET_MAP),
                nllb_worker.NLLB_BATCH_SIZE,
                nllb_worker.NLLB_NUM_BEAMS,
            ),
            daemon=True,
            name=self._PROCESS_NAME,
        )


# Module-level singletons — subprocesses started eagerly at service startup.
_google = _GoogleProcessTranslator()
_nllb   = _NLLBProcessTranslator()

# Round-robin counter for languages with no explicit translate_backend.
# Alternates the primary backend on each call: nllb → google → nllb → …
_rr_counter = itertools.count()


# ---------------------------------------------------------------------------
# Translation telemetry
# ---------------------------------------------------------------------------

class _TranslationStats:
    """Thread-safe counters for translation backend telemetry.

    Tracks routing decisions, per-backend outcomes (ok / perm_fail /
    transient), fallback usage, total call counts and cumulative latency
    so /api/translate can expose precise per-backend statistics.
    """
    __slots__ = (
        '_lock',
        # routing
        'rr_google', 'rr_nllb', 'explicit_google', 'explicit_nllb',
        # google outcomes
        'google_ok', 'google_perm_fail', 'google_transient',
        'google_fallback_primary',          # times google was used as fallback
        # nllb outcomes
        'nllb_ok', 'nllb_perm_fail', 'nllb_transient',
        'nllb_fallback_primary',            # times nllb was used as fallback
        # overall
        'total_ok', 'total_failed',
        # cumulative timing (integer ms to avoid float drift)
        'google_total_ms', 'google_calls',
        'nllb_total_ms',   'nllb_calls',
    )

    def __init__(self) -> None:
        object.__setattr__(self, '_lock', threading.Lock())
        for s in self.__slots__[1:]:
            object.__setattr__(self, s, 0)

    def inc(self, **kwargs: int) -> None:
        """Atomically increment one or more counters."""
        with self._lock:
            for k, v in kwargs.items():
                object.__setattr__(self, k, getattr(self, k) + v)

    def snapshot(self) -> dict:
        """Return a consistent copy of all counters."""
        with self._lock:
            gc = max(self.google_calls, 1)
            nc = max(self.nllb_calls,   1)
            return {
                "google": {
                    "ok":               self.google_ok,
                    "perm_fail":        self.google_perm_fail,
                    "transient_fail":   self.google_transient,
                    "fallback_primary": self.google_fallback_primary,
                    "calls":            self.google_calls,
                    "avg_ms":           round(self.google_total_ms / gc, 1),
                },
                "nllb": {
                    "ok":               self.nllb_ok,
                    "perm_fail":        self.nllb_perm_fail,
                    "transient_fail":   self.nllb_transient,
                    "fallback_primary": self.nllb_fallback_primary,
                    "calls":            self.nllb_calls,
                    "avg_ms":           round(self.nllb_total_ms / nc, 1),
                },
                "routing": {
                    "round_robin_google": self.rr_google,
                    "round_robin_nllb":   self.rr_nllb,
                    "explicit_google":    self.explicit_google,
                    "explicit_nllb":      self.explicit_nllb,
                },
                "totals": {
                    "ok":     self.total_ok,
                    "failed": self.total_failed,
                },
            }


stats = _TranslationStats()


def get_stats() -> dict:
    """Return a snapshot of translation backend telemetry."""
    return stats.snapshot()


def _backend_for(language_code: str | None) -> str | None:
    """Return 'google', 'nllb', or None.
    None means the language has no explicit backend assigned
    (translate_backend IS NULL in the languages table); callers
    should use round-robin or their own fallback."""
    if not language_code:
        return None
    rules = get_language_rules(language_code)
    if rules:
        return rules.get('translate_backend')  # None when DB value is NULL
    return None


# Singleton sentinel returned by _via_google() / _via_nllb() when a backend
# permanently cannot translate a given language (as opposed to a transient
# network or rate-limit failure, which returns None).
_PERM_FAIL = object()

# ---------------------------------------------------------------------------
# Translation orchestration (Google primary → NLLB fallback)
# ---------------------------------------------------------------------------


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split *text* into chunks of at most *max_chars*, preferring paragraph
    then sentence boundaries so translations stay coherent."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        # Prefer paragraph split (\n\n)
        split_at = text.rfind('\n\n', 0, max_chars)
        if split_at == -1:
            # Fall back to sentence boundary
            split_at = text.rfind('. ', 0, max_chars)
        if split_at == -1:
            split_at = max_chars
        else:
            split_at += 2  # include the delimiter
        chunk = text[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        text = text[split_at:].strip()
    return [c for c in chunks if c]


def _translate_via_google_sync(
    fields: list[str],
    non_empty: list[tuple[int, str]],
    target: str,
) -> list[tuple[str, bool]] | None:
    """Send each field as one or more chunked requests to the Google subprocess.
    Returns the results list, None on transient failure, or _PERM_FAIL if
    Google permanently cannot translate this language."""
    results: list[tuple[str, bool]] = [(f, False) for f in fields]
    any_translated = False
    perm_fail = False
    for field_idx, original in non_empty:
        chunks = _chunk_text(original, GOOGLE_MAX_CHARS)
        translated_parts: list[str] = []
        ok = True
        for chunk in chunks:
            logger.debug("[google-sync] → auto→%s [%d chars] %r", target, len(chunk), chunk[:120])
            part = _google.translate_sync(chunk, 'auto', target)
            if part == google_worker.NOLANG:
                logger.info("[google-sync] Language permanently unsupported by Google")
                perm_fail = True
                ok = False
                break
            if part:
                logger.debug("[google-sync] ← %r", part[:120])
                translated_parts.append(part)
            else:
                logger.debug("[google-sync] ← no result for chunk")
                ok = False
                break
        if ok and translated_parts:
            translated = ' '.join(translated_parts)
            was_translated = translated != original
            results[field_idx] = (translated, was_translated)
            if was_translated:
                any_translated = True
    if perm_fail and not any_translated:
        return _PERM_FAIL  # type: ignore[return-value]
    return results if any_translated else None


def _translate_via_nllb_sync(
    fields: list[str],
    non_empty: list[tuple[int, str]],
    source_language_code: str | None,
    target: str,
) -> list[tuple[str, bool]] | None:
    """Send each field as a separate request to the NLLB subprocess.
    Returns the results list, None on transient failure, or _PERM_FAIL if
    NLLB permanently cannot translate this language."""
    src = source_language_code or 'auto'
    results: list[tuple[str, bool]] = [(f, False) for f in fields]
    any_translated = False
    perm_fail = False
    for field_idx, original in non_empty:
        text = original[:MAX_TRANSLATE_CHARS]  # NLLB context limited to ~512 tokens
        logger.debug("[nllb-sync]   → src=%s tgt=%s text=%r", src, target, text[:120])
        translated = _nllb.translate_sync(text, src, target)
        if translated == nllb_worker.NOLANG:
            logger.info("[nllb-sync] Language permanently unsupported by NLLB")
            perm_fail = True
        elif translated and translated != original:
            logger.debug("[nllb-sync]   ← %r", translated[:120])
            results[field_idx] = (translated, True)
            any_translated = True
        else:
            logger.debug("[nllb-sync]   ← no result")
    if perm_fail and not any_translated:
        return _PERM_FAIL  # type: ignore[return-value]
    return results if any_translated else None


def translate_article_fields(
    title: str,
    description: str,
    content: str,
    source_language_code: str | None,
) -> tuple[tuple[str, bool], tuple[str, bool], tuple[str, bool]]:
    """
    Translate title, description and content, alternating between Google
    and NLLB backends on each call.  If the selected backend fails,
    the other backend is used as fallback.

    Returns:
        ((t_title, ok_t), (t_desc, ok_d), (t_cont, ok_c))
    """
    rules = get_language_rules(source_language_code) if source_language_code else None
    if rules is not None and not rules['translate']:
        return (title, False), (description, False), (content, False)

    target = rules['translate_to'] if rules else AUTO_FALLBACK_TARGET
    fields = [title, description, content]
    non_empty = [
        (i, _strip_html(f))
        for i, f in enumerate(fields)
        if f and f.strip()
    ]
    if not non_empty:
        return (title, False), (description, False), (content, False)

    backend = _backend_for(source_language_code)
    _was_rr = backend is None
    if backend is None:
        backend = 'nllb' if next(_rr_counter) % 2 == 0 else 'google'
        logger.debug("[translate-sync] round-robin selected backend=%s for lang=%s", backend, source_language_code)
    logger.debug("[translate-sync] backend=%s lang=%s→%s", backend, source_language_code, target)

    # ── routing telemetry ────────────────────────────────────────────────────
    if _was_rr:
        if backend == 'google': stats.inc(rr_google=1)
        else:                   stats.inc(rr_nllb=1)
    else:
        if backend == 'google': stats.inc(explicit_google=1)
        else:                   stats.inc(explicit_nllb=1)

    if backend == 'google':
        _t0 = _time.perf_counter()
        results = _translate_via_google_sync(fields, non_empty, target)
        stats.inc(google_calls=1, google_total_ms=int((_time.perf_counter() - _t0) * 1000))
        if results is _PERM_FAIL:
            logger.info("[translate-sync] Google permanently unsupported for lang=%s → NLLB", source_language_code)
            stats.inc(google_perm_fail=1)
            _t0 = _time.perf_counter()
            results = _translate_via_nllb_sync(fields, non_empty, source_language_code, target)
            stats.inc(nllb_calls=1, nllb_total_ms=int((_time.perf_counter() - _t0) * 1000), nllb_fallback_primary=1)
            if results is _PERM_FAIL:
                stats.inc(nllb_perm_fail=1, total_failed=1)
                results = None
            elif results is None:
                stats.inc(nllb_transient=1, total_failed=1)
            else:
                stats.inc(nllb_ok=1, total_ok=1)
        elif results is None:
            logger.debug("[translate-sync] google transient failure, falling back to nllb")
            stats.inc(google_transient=1)
            _t0 = _time.perf_counter()
            nllb_r = _translate_via_nllb_sync(fields, non_empty, source_language_code, target)
            stats.inc(nllb_calls=1, nllb_total_ms=int((_time.perf_counter() - _t0) * 1000), nllb_fallback_primary=1)
            results = None if nllb_r is _PERM_FAIL else nllb_r
            if results is None:
                if nllb_r is _PERM_FAIL: stats.inc(nllb_perm_fail=1, total_failed=1)
                else:                    stats.inc(nllb_transient=1,  total_failed=1)
            else:
                stats.inc(nllb_ok=1, total_ok=1)
        else:
            stats.inc(google_ok=1, total_ok=1)
    else:
        _t0 = _time.perf_counter()
        results = _translate_via_nllb_sync(fields, non_empty, source_language_code, target)
        stats.inc(nllb_calls=1, nllb_total_ms=int((_time.perf_counter() - _t0) * 1000))
        if results is _PERM_FAIL:
            logger.info("[translate-sync] NLLB permanently unsupported for lang=%s → Google", source_language_code)
            stats.inc(nllb_perm_fail=1)
            _t0 = _time.perf_counter()
            results = _translate_via_google_sync(fields, non_empty, target)
            stats.inc(google_calls=1, google_total_ms=int((_time.perf_counter() - _t0) * 1000), google_fallback_primary=1)
            if results is _PERM_FAIL:
                stats.inc(google_perm_fail=1, total_failed=1)
                results = None
            elif results is None:
                stats.inc(google_transient=1, total_failed=1)
            else:
                stats.inc(google_ok=1, total_ok=1)
        elif results is None:
            logger.debug("[translate-sync] nllb transient failure, falling back to google")
            stats.inc(nllb_transient=1)
            _t0 = _time.perf_counter()
            google_r = _translate_via_google_sync(fields, non_empty, target)
            stats.inc(google_calls=1, google_total_ms=int((_time.perf_counter() - _t0) * 1000), google_fallback_primary=1)
            results = None if google_r is _PERM_FAIL else google_r
            if results is None:
                if google_r is _PERM_FAIL: stats.inc(google_perm_fail=1, total_failed=1)
                else:                      stats.inc(google_transient=1,  total_failed=1)
            else:
                stats.inc(google_ok=1, total_ok=1)
        else:
            stats.inc(nllb_ok=1, total_ok=1)

    if results is None:
        return (title, False), (description, False), (content, False)
    return tuple(results)  # type: ignore[return-value]


async def translate_article_fields_async(
    title: str,
    description: str,
    content: str,
    source_language_code: str | None,
) -> tuple[tuple[str, bool], tuple[str, bool], tuple[str, bool], str | None]:
    """
    Fully async version of translate_article_fields.

    Returns a 4-tuple:
        (t_title, ok_t), (t_desc, ok_d), (t_cont, ok_c), backend_recommendation

    ``backend_recommendation`` is set to ``'google'`` or ``'nllb'`` when a
    primary backend permanently cannot translate the language (LanguageNotSupportedException
    for Google, unknown lang-code for NLLB) and the other backend succeeded.
    Callers should persist this to ``languages.translate_backend`` so future
    articles skip the failing backend entirely.

    ``backend_recommendation`` is ``None`` for transient failures (network,
    rate-limit, timeout) — those do NOT warrant a permanent DB change.
    """
    rules = get_language_rules(source_language_code) if source_language_code else None
    if rules is not None and not rules['translate']:
        return (title, False), (description, False), (content, False), None

    target   = rules['translate_to'] if rules else AUTO_FALLBACK_TARGET
    fields   = [title, description, content]
    non_empty = [
        (i, _strip_html(f))
        for i, f in enumerate(fields)
        if f and f.strip()
    ]
    if not non_empty:
        return (title, False), (description, False), (content, False), None

    backend = _backend_for(source_language_code)
    _was_rr = backend is None
    if backend is None:
        backend = 'nllb' if next(_rr_counter) % 2 == 0 else 'google'
        logger.debug("[translate-async] round-robin selected backend=%s for lang=%s", backend, source_language_code)
    src     = source_language_code or 'auto'
    logger.debug("[translate-async] backend=%s lang=%s→%s", backend, source_language_code, target)

    # ── routing telemetry ────────────────────────────────────────────────────
    if _was_rr:
        if backend == 'google': stats.inc(rr_google=1)
        else:                   stats.inc(rr_nllb=1)
    else:
        if backend == 'google': stats.inc(explicit_google=1)
        else:                   stats.inc(explicit_nllb=1)

    async def _via_google() -> list[tuple[str, bool]] | None:
        """Returns results list, None (transient), or _PERM_FAIL (permanent lang failure)."""
        res: list[tuple[str, bool]] = [(f, False) for f in fields]
        any_translated = False
        perm_fail = False

        async def _translate_field(field_idx: int, original: str) -> None:
            nonlocal any_translated, perm_fail
            chunks = _chunk_text(original, GOOGLE_MAX_CHARS)
            translated_parts: list[str] = []
            for chunk in chunks:
                logger.debug("[google-async] → auto→%s [%d chars] %r", target, len(chunk), chunk[:120])
                part = await _google.translate_async(chunk, 'auto', target)
                if part == google_worker.NOLANG:
                    logger.info("[google-async] Language permanently unsupported by Google for lang=%s", source_language_code)
                    perm_fail = True
                    return
                if part:
                    logger.debug("[google-async] ← %r", part[:120])
                    translated_parts.append(part)
                else:
                    logger.debug("[google-async] ← no result for chunk")
                    return
            if translated_parts:
                translated = ' '.join(translated_parts)
                if translated != original:
                    res[field_idx] = (translated, True)
                    any_translated = True

        await asyncio.gather(*[_translate_field(fi, orig) for fi, orig in non_empty])
        if perm_fail and not any_translated:
            return _PERM_FAIL  # type: ignore[return-value]
        return res if any_translated else None

    async def _via_nllb() -> list[tuple[str, bool]] | None:
        """Returns results list, None (transient), or _PERM_FAIL (permanent lang failure)."""
        nllb_non_empty = [(fi, orig[:MAX_TRANSLATE_CHARS]) for fi, orig in non_empty]
        for _, original in nllb_non_empty:
            logger.debug("[nllb-async]  → src=%s tgt=%s text=%r", src, target, original[:120])
        tasks = [_nllb.translate_async(original, src, target) for _, original in nllb_non_empty]
        translated_list = await asyncio.gather(*tasks)
        res: list[tuple[str, bool]] = [(f, False) for f in fields]
        any_translated = False
        perm_fail = False
        for (field_idx, original), translated in zip(nllb_non_empty, translated_list):
            if translated == nllb_worker.NOLANG:
                logger.info("[nllb-async]  Language permanently unsupported by NLLB for lang=%s", source_language_code)
                perm_fail = True
            elif translated and translated != original:
                logger.debug("[nllb-async]  ← %r", translated[:120])
                res[field_idx] = (translated, True)
                any_translated = True
            else:
                logger.debug("[nllb-async]  ← no result")
        if perm_fail and not any_translated:
            return _PERM_FAIL  # type: ignore[return-value]
        return res if any_translated else None

    backend_recommendation: str | None = None
    results = None

    if backend == 'google':
        _t0 = _time.perf_counter()
        g_result = await _via_google()
        stats.inc(google_calls=1, google_total_ms=int((_time.perf_counter() - _t0) * 1000))
        if g_result is _PERM_FAIL:
            logger.info("[translate-async] Google permanently unsupported for lang=%s → NLLB", source_language_code)
            stats.inc(google_perm_fail=1)
            _t0 = _time.perf_counter()
            n_result = await _via_nllb()
            stats.inc(nllb_calls=1, nllb_total_ms=int((_time.perf_counter() - _t0) * 1000), nllb_fallback_primary=1)
            results = None if (n_result is None or n_result is _PERM_FAIL) else n_result
            if results is not None:
                backend_recommendation = 'nllb'
                stats.inc(nllb_ok=1, total_ok=1)
            elif n_result is _PERM_FAIL:
                stats.inc(nllb_perm_fail=1, total_failed=1)
            else:
                stats.inc(nllb_transient=1, total_failed=1)
        elif g_result is None:
            logger.debug("[translate-async] google transient failure for lang=%s, falling back to nllb", source_language_code)
            stats.inc(google_transient=1)
            _t0 = _time.perf_counter()
            n_result = await _via_nllb()
            stats.inc(nllb_calls=1, nllb_total_ms=int((_time.perf_counter() - _t0) * 1000), nllb_fallback_primary=1)
            results = None if (n_result is None or n_result is _PERM_FAIL) else n_result
            if results is None:
                if n_result is _PERM_FAIL: stats.inc(nllb_perm_fail=1, total_failed=1)
                else:                      stats.inc(nllb_transient=1,  total_failed=1)
            else:
                stats.inc(nllb_ok=1, total_ok=1)
        else:
            results = g_result
            stats.inc(google_ok=1, total_ok=1)
    else:  # 'nllb'
        _t0 = _time.perf_counter()
        n_result = await _via_nllb()
        stats.inc(nllb_calls=1, nllb_total_ms=int((_time.perf_counter() - _t0) * 1000))
        if n_result is _PERM_FAIL:
            logger.info("[translate-async] NLLB permanently unsupported for lang=%s → Google", source_language_code)
            stats.inc(nllb_perm_fail=1)
            _t0 = _time.perf_counter()
            g_result = await _via_google()
            stats.inc(google_calls=1, google_total_ms=int((_time.perf_counter() - _t0) * 1000), google_fallback_primary=1)
            results = None if (g_result is None or g_result is _PERM_FAIL) else g_result
            if results is not None:
                backend_recommendation = 'google'
                stats.inc(google_ok=1, total_ok=1)
            elif g_result is _PERM_FAIL:
                stats.inc(google_perm_fail=1, total_failed=1)
            else:
                stats.inc(google_transient=1, total_failed=1)
        elif n_result is None:
            logger.debug("[translate-async] nllb transient failure for lang=%s, falling back to google", source_language_code)
            stats.inc(nllb_transient=1)
            _t0 = _time.perf_counter()
            g_result = await _via_google()
            stats.inc(google_calls=1, google_total_ms=int((_time.perf_counter() - _t0) * 1000), google_fallback_primary=1)
            results = None if (g_result is None or g_result is _PERM_FAIL) else g_result
            if results is None:
                if g_result is _PERM_FAIL: stats.inc(google_perm_fail=1, total_failed=1)
                else:                      stats.inc(google_transient=1,  total_failed=1)
            else:
                stats.inc(google_ok=1, total_ok=1)
        else:
            results = n_result
            stats.inc(nllb_ok=1, total_ok=1)

    if results is None:
        return (title, False), (description, False), (content, False), None
    t = tuple(results)
    return t[0], t[1], t[2], backend_recommendation  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

async def _run_tests():
    test_cases = [
        ("es", "El presidente habló sobre la economía"),
        ("fr", "Le président a parlé de l'économie"),
        ("it", "Il presidente ha parlato di economia"),
        ("ro", "Președintele a vorbit despre economie"),
        ("de", "Der Präsident sprach über die Wirtschaft"),
        ("ru", "Президент говорил об экономике"),
        ("zh", "总统谈到了经济问题"),
        ("ar", "تحدث الرئيس عن الاقتصاد"),
        ("ja", "大統領は経済について話した"),
        ("he", "הנשיא דיבר על הכלכלה"),
        ("fa", "رئیس جمهور درباره اقتصاد صحبت کرد"),
        ("en", "Should not be translated"),
        ("pt", "Não deve ser traduzido"),
        ("pt-BR", "Não deve ser traduzido também"),
    ]

    # Also test the auto-detect fallback (None language code)
    test_cases += [
        (None, "Ο πρόεδρος μίλησε για την οικονομία"),   # Greek, unknown to caller
        (None, "This should be unchanged"),               # English via auto
    ]

    ok = fail = skip = 0
    from lang_rules import _load_language_rules
    from google_translate import translate_article_async
    rules = _load_language_rules()
    print(f"{'Code':<10} {'→':^4} {'Target':<8} Result")
    print("-" * 72)
    for code, text in test_cases:
        result, was_translated = await translate_article_async(text, code)
        rule = rules.get(code) if code else None
        if code and rule and not rule['translate']:
            print(f"{str(code):<10} {'→':^4} {'(skip)':<8} ✓ no translation needed")
            skip += 1
            continue
        target = rule['translate_to'] if rule else f'auto→{AUTO_FALLBACK_TARGET}'
        status = "✓" if was_translated else "- unchanged"
        print(f"{str(code):<10} {'→':^4} {target:<8} {status}  {result[:50]}")
        if was_translated:
            ok += 1
        elif code and rule and rule['translate']:
            fail += 1
        # auto-detect cases: not a failure if unchanged (likely already English)

    print(f"\nResult: {ok} translated, {skip} skipped (no translation needed), {fail} failed")


if __name__ == "__main__":
    asyncio.run(_run_tests())
