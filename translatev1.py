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
import multiprocessing
import re
import threading
import uuid

import google_worker
import nllb_worker
from lang_rules import AUTO_FALLBACK_TARGET, _load_language_rules, get_language_rules
from text_utils import MAX_TRANSLATE_CHARS, _strip_html

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
        assert self._resp_q is not None
        while not self._shutdown.is_set():
            try:
                item = self._resp_q.get(timeout=0.5)
            except Exception:
                continue
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

    async def translate_async(
        self, text: str, src_code: str, tgt_code: str
    ) -> str | None:
        """
        Non-blocking translation for use inside an asyncio event loop.
        Returns the translated string, or None on failure.
        """
        if self._shutdown.is_set():
            return None
        self._ensure_started()
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        req_id = str(uuid.uuid4())
        fut: asyncio.Future[str | None] = loop.create_future()
        with self._lock:
            self._async_pending[req_id] = fut
        assert self._req_q is not None
        self._req_q.put((req_id, text, src_code, tgt_code))
        return await fut


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
            ),
            daemon=True,
            name=self._PROCESS_NAME,
        )


# Module-level singletons — subprocesses started eagerly at service startup.
_google = _GoogleProcessTranslator()
_nllb   = _NLLBProcessTranslator()


# ---------------------------------------------------------------------------
# Translation orchestration (Google primary → NLLB fallback)
# ---------------------------------------------------------------------------


def translate_article_fields(
    title: str,
    description: str,
    content: str,
    source_language_code: str | None,
) -> tuple[tuple[str, bool], tuple[str, bool], tuple[str, bool]]:
    """
    Translate title, description, and content in a **single** API call by
    concatenating them with a unique separator, translating the whole block,
    then splitting the result.

    Returns:
        ((t_title, ok_t), (t_desc, ok_d), (t_cont, ok_c))
    """
    # Resolve translation rules once
    rules = get_language_rules(source_language_code) if source_language_code else None

    if rules is not None and not rules['translate']:
        # Language known and not translatable (en/pt/etc.) → skip all fields
        return (title, False), (description, False), (content, False)

    target = rules['translate_to'] if rules else AUTO_FALLBACK_TARGET

    # Build the list of non-empty fields to translate, keeping their index
    fields = [title, description, content]
    non_empty = [(i, _strip_html(f)[:MAX_TRANSLATE_CHARS]) for i, f in enumerate(fields) if f and f.strip()]

    if not non_empty:
        return (title, False), (description, False), (content, False)

    # Concatenate into one request
    combined = _FIELD_SEP.join(text for _, text in non_empty)

    translated_combined = _google.translate_sync(combined, 'auto', target)

    if not translated_combined:
        # Google failed — fall back to NLLB subprocess
        src = source_language_code or 'auto'
        results: list[tuple[str, bool]] = [(f, False) for f in fields]
        for field_idx, original in non_empty:
            translated = _nllb.translate_sync(original, src, target)
            if translated and translated != original:
                results[field_idx] = (translated, True)
        return tuple(results)  # type: ignore[return-value]

    # Split translated result back by separator (Google may add spaces around it)
    parts = re.split(r'\s*<<<SEP>>>\s*', translated_combined)

    results = [(f, False) for f in fields]
    for idx, (field_idx, original) in enumerate(non_empty):
        translated = parts[idx].strip() if idx < len(parts) else ''
        was_translated = bool(translated) and translated != original
        results[field_idx] = (translated if translated else fields[field_idx], was_translated)

    return tuple(results)  # type: ignore[return-value]


async def translate_article_fields_async(
    title: str,
    description: str,
    content: str,
    source_language_code: str | None,
) -> tuple[tuple[str, bool], tuple[str, bool], tuple[str, bool]]:
    """
    Fully async version of translate_article_fields.

    * Google Translate is called in a thread-pool executor (it's blocking IO).
    * If Google fails, the NLLB subprocess is used via translate_async() —
      all non-empty fields are sent concurrently, so total latency is
      max(field_latencies) rather than their sum.
    """
    rules = get_language_rules(source_language_code) if source_language_code else None
    if rules is not None and not rules['translate']:
        return (title, False), (description, False), (content, False)

    target   = rules['translate_to'] if rules else AUTO_FALLBACK_TARGET
    fields   = [title, description, content]
    non_empty = [
        (i, _strip_html(f)[:MAX_TRANSLATE_CHARS])
        for i, f in enumerate(fields)
        if f and f.strip()
    ]
    if not non_empty:
        return (title, False), (description, False), (content, False)

    # ── Google Translate subprocess (batch, single request) ──────────────
    combined = _FIELD_SEP.join(text for _, text in non_empty)
    translated_combined: str | None = await _google.translate_async(combined, 'auto', target)

    if translated_combined:
        parts = re.split(r'\s*<<<SEP>>>\s*', translated_combined)
        results: list[tuple[str, bool]] = [(f, False) for f in fields]
        for idx, (field_idx, original) in enumerate(non_empty):
            translated = parts[idx].strip() if idx < len(parts) else ''
            was_translated = bool(translated) and translated != original
            results[field_idx] = (translated or fields[field_idx], was_translated)
        return tuple(results)  # type: ignore[return-value]

    # ── NLLB fallback (concurrent async requests to the GPU subprocess) ───
    src = source_language_code or 'auto'
    tasks = [_nllb.translate_async(original, src, target) for _, original in non_empty]
    translated_list = await asyncio.gather(*tasks)
    results = [(f, False) for f in fields]
    for (field_idx, original), translated in zip(non_empty, translated_list):
        if translated and translated != original:
            results[field_idx] = (translated, True)
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
