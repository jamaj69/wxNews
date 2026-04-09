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
    # Target language codes used in translate_to column
    'por_Latn': 'por_Latn',
    'eng_Latn': 'eng_Latn',
}

NLLB_TARGET_MAP: dict[str, str] = {
    'pt': 'por_Latn',
    'en': 'eng_Latn',
}

NLLB_MODEL_ID = "facebook/nllb-200-distilled-1.3B"


# ---------------------------------------------------------------------------
# Worker entry-point
# ---------------------------------------------------------------------------

def worker(
    req_q: "multiprocessing.Queue[tuple | None]",
    resp_q: "multiprocessing.Queue[tuple]",
    model_id: str,
    lang_map: dict,
    target_map: dict,
) -> None:
    """
    GPU worker process.  Loads the NLLB model once, then processes translation
    requests indefinitely until a ``None`` sentinel is received.

    Protocol
    --------
    request:  ``(req_id: str, text: str, src_code: str, tgt_code: str)``
            | ``None``   ← shutdown sentinel
    response: ``(req_id: str, translated_str_or_None)``
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # parent handles SIGINT

    model = tokenizer = device = None
    ready = False

    def _load() -> bool:
        nonlocal model, tokenizer, device, ready
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            print(f"[nllb-worker] Loading {model_id} on {device} …", flush=True)
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            model = AutoModelForSeq2SeqLM.from_pretrained(model_id).to(device)
            model.eval()
            print(f"[nllb-worker] Ready on {device}", flush=True)
            ready = True
            return True
        except Exception as e:
            print(f"[nllb-worker] Load failed: {e}", flush=True)
            return False

    _load()

    while True:
        try:
            item = req_q.get()
        except (EOFError, OSError):
            break
        if item is None:          # shutdown sentinel
            break

        req_id, text, src_code, tgt_code = item
        result = None

        if ready and text and text.strip():
            src_nllb = lang_map.get((src_code or "").lower())
            tgt_nllb = target_map.get(tgt_code) or lang_map.get(tgt_code)
            if src_nllb and tgt_nllb:
                print(
                    f"[nllb-worker] → {src_code}({src_nllb})→{tgt_nllb} | {text.strip()[:120]!r}",
                    flush=True,
                )
                try:
                    import torch
                    tokenizer.src_lang = src_nllb
                    inputs = tokenizer(
                        text.strip(), return_tensors="pt",
                        padding=True, truncation=True, max_length=512,
                    ).to(device)
                    forced_bos = tokenizer.convert_tokens_to_ids(tgt_nllb)
                    with torch.no_grad():
                        output_ids = model.generate(
                            **inputs,
                            forced_bos_token_id=forced_bos,
                            max_new_tokens=512,
                            max_length=None,   # silence conflict with generation_config default
                        )
                    translated = tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0]
                    result = translated.strip() or None
                    print(
                        f"[nllb-worker] ← {(result or '').strip()[:120]!r}",
                        flush=True,
                    )
                except Exception as e:
                    print(f"[nllb-worker] Inference error: {str(e)[:200]}", flush=True)
            else:
                print(f"[nllb-worker] Unknown lang: src={src_code!r} tgt={tgt_code!r}", flush=True)

        resp_q.put((req_id, result))

    print("[nllb-worker] Exiting.", flush=True)
