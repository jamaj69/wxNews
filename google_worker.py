#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Translate worker process.

Kept intentionally thin so that Python's ``spawn`` start method does not
need to import ``deep_translator`` (or any other heavy dependency) in the
parent process.  All imports happen inside the ``worker()`` function after
the child process is spawned.

Spawned by ``translatev1._GoogleProcessTranslator._ensure_started()``.
"""

import multiprocessing
import signal


def worker(
    req_q: "multiprocessing.Queue[tuple | None]",
    resp_q: "multiprocessing.Queue[tuple]",
) -> None:
    """
    Google Translate worker process.  Idle until a translation request
    arrives on *req_q*, translates it with GoogleTranslator, then puts
    the result on *resp_q*.

    Protocol
    --------
    request:  ``(req_id: str, text: str, src_code: str, tgt_code: str)``
            | ``None``   ← shutdown sentinel
    response: ``(req_id: str, translated_str_or_None)``
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # parent handles SIGINT

    try:
        from deep_translator import GoogleTranslator
        from deep_translator.exceptions import LanguageNotSupportedException
    except Exception as e:
        print(f"[google-worker] Import failed: {e}", flush=True)
        # Drain queue and signal failure for every request so callers unblock.
        while True:
            try:
                item = req_q.get()
            except (EOFError, OSError):
                return
            if item is None:
                return
            resp_q.put((item[0], None))
        return  # unreachable but explicit

    print("[google-worker] Ready", flush=True)

    while True:
        try:
            item = req_q.get()
        except (EOFError, OSError):
            break
        if item is None:          # shutdown sentinel
            break

        req_id, text, src_code, tgt_code = item
        result = None

        if text and text.strip():
            print(
                f"[google-worker] → {src_code}→{tgt_code} | {text.strip()[:120]!r}",
                flush=True,
            )
            try:
                result = GoogleTranslator(
                    source=src_code, target=tgt_code
                ).translate(text.strip())
                print(
                    f"[google-worker] ← {(result or '').strip()[:120]!r}",
                    flush=True,
                )
            except LanguageNotSupportedException as e:
                print(
                    f"[google-worker] Language not supported {src_code}→{tgt_code}: {e}",
                    flush=True,
                )
            except Exception as e:
                print(
                    f"[google-worker] Error {src_code}→{tgt_code}: {str(e)[:200]}",
                    flush=True,
                )

        resp_q.put((req_id, result))
