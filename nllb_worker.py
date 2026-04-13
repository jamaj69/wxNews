#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NLLB-200 GPU worker process.

This module is kept intentionally thin so that Python's ``spawn`` start
method does not need to import the heavy ``translatev1`` module inside the
child process.  Only ``torch`` and ``transformers`` are imported here, and
only after the worker function is actually called.

Spawned by ``translatev1._NLLBProcessTranslator._ensure_started()``.
"""

import multiprocessing
import signal

# ---------------------------------------------------------------------------
# Language-code maps
# ---------------------------------------------------------------------------

NLLB_LANG_MAP: dict[str, str] = {
    'bn':    'ben_Beng',  # Bengali
    'ar':    'arb_Arab',  # Arabic
    'fa':    'pes_Arab',  # Persian / Farsi
    'hi':    'hin_Deva',  # Hindi
    'ur':    'urd_Arab',  # Urdu
    'zh-cn': 'zho_Hans',  # Chinese Simplified
    'zh-tw': 'zho_Hant',  # Chinese Traditional
    'zh':    'zho_Hans',
    'ja':    'jpn_Jpan',  # Japanese
    'ko':    'kor_Hang',  # Korean
    'ru':    'rus_Cyrl',  # Russian
    'iw':    'heb_Hebr',  # Hebrew (Google code)
    'he':    'heb_Hebr',
    'tr':    'tur_Latn',  # Turkish
    'id':    'ind_Latn',  # Indonesian
    'th':    'tha_Thai',  # Thai
    'vi':    'vie_Latn',  # Vietnamese
    'ms':    'zsm_Latn',  # Malay
    'am':    'amh_Ethi',  # Amharic
    'sw':    'swh_Latn',  # Swahili
    'so':    'som_Latn',  # Somali
    'tl':    'tgl_Latn',  # Tagalog / Filipino
    'uk':    'ukr_Cyrl',  # Ukrainian
    'pl':    'pol_Latn',  # Polish
    'nl':    'nld_Latn',  # Dutch
    'de':    'deu_Latn',  # German
    'fr':    'fra_Latn',  # French
    'es':    'spa_Latn',  # Spanish
    'it':    'ita_Latn',  # Italian
    'pt':    'por_Latn',  # Portuguese
    'en':    'eng_Latn',  # English
    'cy':    'cym_Latn',  # Welsh
    'ca':    'cat_Latn',  # Catalan
    'sv':    'swe_Latn',  # Swedish
    'da':    'dan_Latn',  # Danish
    'af':    'afr_Latn',  # Afrikaans
    'no':    'nob_Latn',  # Norwegian Bokmål
    'et':    'est_Latn',  # Estonian
    'hu':    'hun_Latn',  # Hungarian
    'ro':    'ron_Latn',  # Romanian
    'cs':    'ces_Latn',  # Czech
    'sk':    'slk_Latn',  # Slovak
    'fi':    'fin_Latn',  # Finnish
    'lt':    'lit_Latn',  # Lithuanian
    'lv':    'lvs_Latn',  # Latvian
    'bg':    'bul_Cyrl',  # Bulgarian
    'hr':    'hrv_Latn',  # Croatian
    'sr':    'srp_Cyrl',  # Serbian
    'sl':    'slv_Latn',  # Slovenian
    'el':    'ell_Grek',  # Greek
    # Target language codes used in translate_to column
    'por_Latn': 'por_Latn',
    'eng_Latn': 'eng_Latn',
}

NLLB_TARGET_MAP: dict[str, str] = {
    'pt': 'por_Latn',
    'en': 'eng_Latn',
}

NLLB_MODEL_ID  = "facebook/nllb-200-distilled-600M"

# Configurable via NLLB_BATCH_SIZE env var (or override after import).
# 600M model uses ~2.5 GB VRAM on a 6 GB card, leaving ~3.3 GB free.
# batch_size=16 is safe; increase to 32 if VRAM allows.
import os as _os
NLLB_BATCH_SIZE: int = int(_os.environ.get("NLLB_BATCH_SIZE", 16))


# ---------------------------------------------------------------------------
# Worker entry-point
# ---------------------------------------------------------------------------

def worker(
    req_q: "multiprocessing.Queue[tuple | None]",
    resp_q: "multiprocessing.Queue[tuple]",
    model_id: str,
    lang_map: dict,
    target_map: dict,
    batch_size: int = 8,
) -> None:
    """
    GPU worker process.  Loads the NLLB model once, then processes translation
    requests indefinitely until a ``None`` sentinel is received.

    Requests are batched: after the first item arrives the worker drains the
    queue (non-blocking) up to ``batch_size`` items, groups them by
    (src_lang, tgt_lang) pair, and runs a single ``model.generate()`` per
    group so the GPU is saturated rather than processing one item at a time.

    Protocol
    --------
    request:  ``(req_id: str, text: str, src_code: str, tgt_code: str)``
            | ``None``   ← shutdown sentinel
    response: ``(req_id: str, translated_str_or_None)``
    """
    import queue as _queue
    import time as _time

    signal.signal(signal.SIGINT, signal.SIG_IGN)   # parent handles SIGINT

    model = tokenizer = device = None
    ready = False

    def _load() -> bool:
        nonlocal model, tokenizer, device, ready
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            print(f"[nllb-worker] Loading {model_id} on {device} (batch_size={batch_size}) …", flush=True)
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            model = AutoModelForSeq2SeqLM.from_pretrained(model_id).to(device)
            model.eval()
            print(f"[nllb-worker] Ready on {device}", flush=True)
            ready = True
            return True
        except Exception as e:
            print(f"[nllb-worker] Load failed: {e}", flush=True)
            return False

    def _translate_group(texts: list[str], src_nllb: str, tgt_nllb: str) -> list[str | None]:
        """Run batched inference for a group sharing the same lang pair."""
        import torch
        try:
            tokenizer.src_lang = src_nllb
            forced_bos = tokenizer.convert_tokens_to_ids(tgt_nllb)
            inputs = tokenizer(
                texts, return_tensors="pt",
                padding=True, truncation=True, max_length=512,
            ).to(device)
            with torch.no_grad():
                output_ids = model.generate(
                    **inputs,
                    forced_bos_token_id=forced_bos,
                    max_new_tokens=512,
                    max_length=None,
                    num_beams=4,
                )
            decoded = tokenizer.batch_decode(output_ids, skip_special_tokens=True)
            return [s.strip() or None for s in decoded]
        except Exception as e:
            print(f"[nllb-worker] Inference error: {str(e)[:200]}", flush=True)
            return [None] * len(texts)

    _load()

    shutdown = False
    while not shutdown:
        # ── collect up to batch_size items ───────────────────────────────────
        # After the first item arrives, wait up to FILL_TIMEOUT seconds so
        # more items accumulate in the queue before running generate().
        # This smooths out GPU spikes caused by serial async senders.
        FILL_TIMEOUT = 0.3   # seconds to wait for queue to fill up

        items: list[tuple] = []
        try:
            first = req_q.get()          # blocks until at least one arrives
        except (EOFError, OSError):
            break
        if first is None:
            break
        items.append(first)

        # drain remaining up to batch_size-1 more, waiting up to FILL_TIMEOUT
        deadline = _time.monotonic() + FILL_TIMEOUT
        while len(items) < batch_size:
            timeout = deadline - _time.monotonic()
            if timeout <= 0:
                break
            try:
                item = req_q.get(timeout=timeout)
            except _queue.Empty:
                break
            if item is None:
                shutdown = True          # process remaining items then exit
                break
            items.append(item)

        if not items:
            break

        # ── group by (src_nllb, tgt_nllb) ────────────────────────────────────
        # items that can't be mapped are sent back as None immediately
        groups: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
        results: dict[str, str | None] = {}

        for req_id, text, src_code, tgt_code in items:
            src_nllb = lang_map.get((src_code or "").lower())
            tgt_nllb = target_map.get(tgt_code) or lang_map.get(tgt_code)
            if not ready or not text or not text.strip() or not src_nllb or not tgt_nllb:
                if not src_nllb or not tgt_nllb:
                    print(f"[nllb-worker] Unknown lang: src={src_code!r} tgt={tgt_code!r}", flush=True)
                results[req_id] = None
                continue
            key = (src_nllb, tgt_nllb)
            groups.setdefault(key, []).append((req_id, text.strip(), src_code))

        # ── run inference per group ───────────────────────────────────────────
        for (src_nllb, tgt_nllb), group_items in groups.items():
            req_ids  = [g[0] for g in group_items]
            texts    = [g[1] for g in group_items]
            src_code = group_items[0][2]
            print(
                f"[nllb-worker] batch {len(texts)} × {src_code}→{tgt_nllb.split('_')[0]} "
                f"| {texts[0][:80]!r}{'…' if len(texts)>1 else ''}",
                flush=True,
            )
            translated = _translate_group(texts, src_nllb, tgt_nllb)
            for req_id, result in zip(req_ids, translated):
                results[req_id] = result
                if result:
                    print(f"[nllb-worker] ← {result[:80]!r}", flush=True)

        # ── dispatch responses in original order ──────────────────────────────
        for req_id, _, _, _ in items:
            resp_q.put((req_id, results.get(req_id)))

    print("[nllb-worker] Exiting.", flush=True)
