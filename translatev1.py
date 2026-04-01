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


def translate_article(text: str, source_language_code: str) -> str:
    """
    Translate *text* according to the rules stored in the languages table.

    Looks up *source_language_code* in the DB:
      - If no rule exists, or translate=False, returns text as-is.
      - Otherwise translates to the configured target language.
    """
    rules = get_language_rules(source_language_code)
    if rules is None or not rules['translate']:
        return text
    return translate_text(
        text,
        source_lang=rules['translator_code'],
        target_lang=rules['translate_to'],
    )


# ---------------------------------------------------------------------------
# Async wrappers (for use inside asyncio event loops)
# ---------------------------------------------------------------------------

async def translate_text_async(text: str, source_lang: str, target_lang: str) -> str:
    """Async wrapper around translate_text (runs in executor to avoid blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, translate_text, text, source_lang, target_lang)


async def translate_article_async(text: str, source_language_code: str) -> str:
    """Async wrapper around translate_article."""
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

    ok = fail = skip = 0
    rules = _load_language_rules()
    print(f"{'Code':<8} {'→':^4} {'Target':<8} Result")
    print("-" * 70)
    for code, text in test_cases:
        rule = rules.get(code)
        if rule is None:
            print(f"{code:<8} {'→':^4} {'?':<8} ⚠ no rule in DB")
            fail += 1
            continue
        if not rule['translate']:
            print(f"{code:<8} {'→':^4} {'(skip)':<8} ✓ no translation needed")
            skip += 1
            continue
        result = await translate_article_async(text, code)
        success = result != text
        status = "✓" if success else "⚠ unchanged"
        print(f"{code:<8} {'→':^4} {rule['translate_to']:<8} {status}  {result[:55]}")
        if success:
            ok += 1
        else:
            fail += 1

    print(f"\nResult: {ok} translated, {skip} skipped (no translation needed), {fail} failed")


if __name__ == "__main__":
    asyncio.run(_run_tests())
