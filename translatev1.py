#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Translation utilities using deep-translator (GoogleTranslator backend).

Language rules are read from the `languages` table in the database:
  - translate=0  → no translation needed (en, pt, pt-BR)
  - translate=1  → translate to translate_to ('pt' for Romance langs, 'en' otherwise)
  - translator_code → deep-translator compatible code (e.g. zh-CN, iw)
"""

import asyncio
import sqlite3
from functools import lru_cache
from deep_translator import GoogleTranslator
from deep_translator.exceptions import LanguageNotSupportedException

DB_PATH = "predator_news.db"


# ---------------------------------------------------------------------------
# Language rules cache
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_language_rules() -> dict:
    """
    Returns a dict keyed by language_code with translation rules.
    Shape: { 'es': {'translate': True, 'translate_to': 'pt', 'translator_code': 'es'}, ... }
    """
    rules = {}
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("""
            SELECT language_code, translator_code, translate, translate_to
            FROM languages
        """)
        for row in cur.fetchall():
            rules[row['language_code']] = {
                'translate': bool(row['translate']),
                'translate_to': row['translate_to'],
                'translator_code': row['translator_code'] or row['language_code'],
            }
        con.close()
    except Exception as e:
        print(f"[translate] Warning: could not load language rules: {e}")
    return rules


def get_language_rules(language_code: str) -> dict | None:
    """Return translation rule for the given language_code, or None if unknown."""
    return _load_language_rules().get(language_code)


# ---------------------------------------------------------------------------
# Core translation
# ---------------------------------------------------------------------------

def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    """
    Translate *text* from *source_lang* to *target_lang* using GoogleTranslator.

    *source_lang* and *target_lang* should be deep-translator compatible codes
    (use the `translator_code` field from the languages table, not language_code).

    Returns translated text, or the original text on any error.
    """
    if not text or not text.strip():
        return text
    if source_lang == target_lang:
        return text
    try:
        translated = GoogleTranslator(source=source_lang, target=target_lang).translate(text)
        return translated or text
    except LanguageNotSupportedException as e:
        print(f"[translate] Language not supported: {source_lang}→{target_lang}: {e}")
        return text
    except Exception as e:
        print(f"[translate] Error translating {source_lang}→{target_lang}: {e}")
        return text


# Default target when language detection failed or code is unknown.
AUTO_FALLBACK_TARGET = "en"


def translate_article(text: str, source_language_code: str | None) -> tuple[str, bool]:
    """
    Translate *text* according to the rules stored in the languages table.

    Returns (translated_text, was_translated):
      - was_translated=False → caller should store NULL in translated_* columns
      - was_translated=True  → caller should store the result and set is_translated=1

    Decision logic:
      1. Known language, translate=False (en/pt/pt-BR) → no translation
      2. Known language, translate=True                → translate to configured target
      3. NULL / unknown language                       → auto-detect via Google, target=en
         If the result is identical to the input, the article was already in the
         target language, so was_translated is returned as False.
    """
    if not text or not text.strip():
        return text, False

    rules = get_language_rules(source_language_code) if source_language_code else None

    if rules is not None:
        # Language known — apply stored rule
        if not rules['translate']:
            return text, False
        result = translate_text(text, rules['translator_code'], rules['translate_to'])
        return result, result != text

    # Language unknown / detection failed — let Google auto-detect
    result = translate_text(text, 'auto', AUTO_FALLBACK_TARGET)
    was_translated = result != text
    return result, was_translated


# ---------------------------------------------------------------------------
# Async wrappers (for use inside asyncio event loops)
# ---------------------------------------------------------------------------

async def translate_text_async(text: str, source_lang: str, target_lang: str) -> str:
    """Async wrapper around translate_text (runs in executor to avoid blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, translate_text, text, source_lang, target_lang)


async def translate_article_async(text: str, source_language_code: str | None) -> tuple[str, bool]:
    """Async wrapper around translate_article. Returns (translated_text, was_translated)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, translate_article, text, source_language_code)


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
