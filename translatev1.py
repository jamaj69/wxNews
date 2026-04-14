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

def _backend_for(language_code: str | None) -> str:
    """Return 'google' or 'nllb' based on the translate_backend column in the
    languages table.  Falls back to 'nllb' for unknown languages."""
    if not language_code:
        return 'nllb'
    rules = get_language_rules(language_code)
    if rules and rules.get('translate_backend'):
        return rules['translate_backend']
    return 'nllb'


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
    Returns the results list, or None if every field failed."""
    results: list[tuple[str, bool]] = [(f, False) for f in fields]
    any_translated = False
    for field_idx, original in non_empty:
        chunks = _chunk_text(original, GOOGLE_MAX_CHARS)
        translated_parts: list[str] = []
        ok = True
        for chunk in chunks:
            logger.debug("[google-sync] → auto→%s [%d chars] %r", target, len(chunk), chunk[:120])
            part = _google.translate_sync(chunk, 'auto', target)
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
    return results if any_translated else None


def _translate_via_nllb_sync(
    fields: list[str],
    non_empty: list[tuple[int, str]],
    source_language_code: str | None,
    target: str,
) -> list[tuple[str, bool]] | None:
    """Send each field as a separate request to the NLLB subprocess.
    Returns the results list, or None if all fields failed."""
    src = source_language_code or 'auto'
    results: list[tuple[str, bool]] = [(f, False) for f in fields]
    any_translated = False
    for field_idx, original in non_empty:
        text = original[:MAX_TRANSLATE_CHARS]  # NLLB context limited to ~512 tokens
        logger.debug("[nllb-sync]   → src=%s tgt=%s text=%r", src, target, text[:120])
        translated = _nllb.translate_sync(text, src, target)
        if translated and translated != original:
            logger.debug("[nllb-sync]   ← %r", translated[:120])
            results[field_idx] = (translated, True)
            any_translated = True
        else:
            logger.debug("[nllb-sync]   ← no result")
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
    logger.debug("[translate-sync] backend=%s lang=%s→%s", backend, source_language_code, target)

    if backend == 'google':
        results = _translate_via_google_sync(fields, non_empty, target)
        if results is None:
            logger.debug("[translate-sync] google failed, falling back to nllb")
            results = _translate_via_nllb_sync(fields, non_empty, source_language_code, target)
    else:
        results = _translate_via_nllb_sync(fields, non_empty, source_language_code, target)
        if results is None:
            logger.debug("[translate-sync] nllb failed, falling back to google")
            results = _translate_via_google_sync(fields, non_empty, target)

    if results is None:
        return (title, False), (description, False), (content, False)
    return tuple(results)  # type: ignore[return-value]


async def translate_article_fields_async(
    title: str,
    description: str,
    content: str,
    source_language_code: str | None,
) -> tuple[tuple[str, bool], tuple[str, bool], tuple[str, bool]]:
    """
    Fully async version of translate_article_fields.

    Alternates between Google and NLLB backends on each call.
    If the selected backend fails, the other is used as fallback.

    Google: all fields batched in one request (fast, single round-trip).
    NLLB:   each field sent as a separate request, all concurrent via asyncio.gather.
    """
    rules = get_language_rules(source_language_code) if source_language_code else None
    if rules is not None and not rules['translate']:
        return (title, False), (description, False), (content, False)

    target   = rules['translate_to'] if rules else AUTO_FALLBACK_TARGET
    fields   = [title, description, content]
    non_empty = [
        (i, _strip_html(f))
        for i, f in enumerate(fields)
        if f and f.strip()
    ]
    if not non_empty:
        return (title, False), (description, False), (content, False)

    backend = _backend_for(source_language_code)
    src     = source_language_code or 'auto'
    logger.debug("[translate-async] backend=%s lang=%s→%s", backend, source_language_code, target)

    async def _via_google() -> list[tuple[str, bool]] | None:
        res: list[tuple[str, bool]] = [(f, False) for f in fields]
        any_translated = False

        async def _translate_field(field_idx: int, original: str) -> None:
            chunks = _chunk_text(original, GOOGLE_MAX_CHARS)
            translated_parts: list[str] = []
            for chunk in chunks:
                logger.debug("[google-async] → auto→%s [%d chars] %r", target, len(chunk), chunk[:120])
                part = await _google.translate_async(chunk, 'auto', target)
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
                    nonlocal any_translated
                    any_translated = True

        await asyncio.gather(*[_translate_field(fi, orig) for fi, orig in non_empty])
        return res if any_translated else None

    async def _via_nllb() -> list[tuple[str, bool]] | None:
        nllb_non_empty = [(fi, orig[:MAX_TRANSLATE_CHARS]) for fi, orig in non_empty]
        for _, original in nllb_non_empty:
            logger.debug("[nllb-async]  → src=%s tgt=%s text=%r", src, target, original[:120])
        tasks = [_nllb.translate_async(original, src, target) for _, original in nllb_non_empty]
        translated_list = await asyncio.gather(*tasks)
        res: list[tuple[str, bool]] = [(f, False) for f in fields]
        any_translated = False
        for (field_idx, original), translated in zip(nllb_non_empty, translated_list):
            if translated and translated != original:
                logger.debug("[nllb-async]  ← %r", translated[:120])
                res[field_idx] = (translated, True)
                any_translated = True
            else:
                logger.debug("[nllb-async]  ← no result")
        return res if any_translated else None

    if backend == 'google':
        results = await _via_google()
        if results is None:
            logger.debug("[translate-async] google failed, falling back to nllb")
            results = await _via_nllb()
    else:
        results = await _via_nllb()
        if results is None:
            logger.debug("[translate-async] nllb failed, falling back to google")
            results = await _via_google()

    if results is None:
        return (title, False), (description, False), (content, False)
    return tuple(results)  # type: ignore[return-value]


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
