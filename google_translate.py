#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Translate backend.

Wraps ``deep-translator`` GoogleTranslator.  Language-rule lookups are
delegated to ``lang_rules``; text pre-processing to ``text_utils``.

Public API
----------
* ``translate_text()``          — single-string, blocking.
* ``translate_article()``       — rule-driven, blocking.
* ``translate_batch()``         — pre-combined multi-field string, blocking.
* ``translate_text_async()``    — async wrapper around translate_text.
* ``translate_article_async()`` — async wrapper around translate_article.
* ``translate_batch_async()``   — async wrapper around translate_batch.
"""

import asyncio

from deep_translator import GoogleTranslator
from deep_translator.exceptions import LanguageNotSupportedException

from lang_rules import AUTO_FALLBACK_TARGET, get_language_rules
from text_utils import MAX_TRANSLATE_CHARS, _strip_html

# Separator used to batch multiple article fields in a single API call.
# Chosen to be visually distinct and very unlikely to appear in article text.
_FIELD_SEP = "\n\n<<<SEP>>>\n\n"


def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    """
    Translate *text* from *source_lang* to *target_lang* using GoogleTranslator.

    *source_lang* and *target_lang* should be deep-translator compatible codes
    (use the ``translator_code`` field from the languages table, not language_code).

    Returns translated text, or the original text on any error.
    """
    if not text or not text.strip():
        return text
    if source_lang == target_lang:
        return text
    clean = _strip_html(text)
    if not clean:
        return text
    clean = clean[:MAX_TRANSLATE_CHARS]
    try:
        translated = GoogleTranslator(source=source_lang, target=target_lang).translate(clean)
        return translated or text
    except LanguageNotSupportedException as e:
        print(f"[google] Language not supported: {source_lang}→{target_lang}: {e}")
        return text
    except Exception as e:
        print(f"[google] Error translating {source_lang}→{target_lang}: {str(e)[:200]}")
        return text


def translate_article(text: str, source_language_code: str | None) -> tuple[str, bool]:
    """
    Translate *text* according to the rules stored in the languages table.

    Returns ``(translated_text, was_translated)``:
      - ``was_translated=False`` → caller should store NULL in translated_* columns.
      - ``was_translated=True``  → caller should store the result and set is_translated=1.

    Decision logic:
      1. Known language, translate=False (en/pt/pt-BR) → no translation.
      2. Known language, translate=True                → translate to configured target.
      3. NULL / unknown language                       → auto-detect via Google, target=en.
         If the result is identical to the input, the article was already in the
         target language, so ``was_translated`` is returned as False.
    """
    if not text or not text.strip():
        return text, False

    rules = get_language_rules(source_language_code) if source_language_code else None

    if rules is not None:
        if not rules['translate']:
            return text, False
        clean_input = _strip_html(text)[:MAX_TRANSLATE_CHARS]
        result = translate_text(text, 'auto', rules['translate_to'])
        return result, bool(result) and result != clean_input

    clean_input = _strip_html(text)[:MAX_TRANSLATE_CHARS]
    result = translate_text(text, 'auto', AUTO_FALLBACK_TARGET)
    was_translated = bool(result) and result != clean_input
    return result, was_translated


def translate_batch(combined: str, target: str) -> str | None:
    """
    Translate a pre-combined multi-field string with ``source='auto'``.

    Used by the orchestration layer (``translatev1``) to send all article
    fields in a single API call.  Returns None on any failure so the caller
    can fall back to the NLLB backend.
    """
    if not combined or not combined.strip():
        return None
    try:
        return GoogleTranslator(source='auto', target=target).translate(combined)
    except LanguageNotSupportedException as e:
        print(f"[google] Language not supported: auto→{target}: {e}")
        return None
    except Exception as e:
        print(f"[google] Error translating auto→{target}: {str(e)[:200]}")
        return None


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------

async def translate_text_async(text: str, source_lang: str, target_lang: str) -> str:
    """Async wrapper around translate_text (runs in executor to avoid blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, translate_text, text, source_lang, target_lang)


async def translate_article_async(
    text: str, source_language_code: str | None
) -> tuple[str, bool]:
    """Async wrapper around translate_article. Returns (translated_text, was_translated)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, translate_article, text, source_language_code)


async def translate_batch_async(combined: str, target: str) -> str | None:
    """Non-blocking wrapper around translate_batch (Google IO in executor)."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, translate_batch, combined, target)
    except Exception as e:
        print(f"[google] Async batch error auto→{target}: {str(e)[:200]}")
        return None
