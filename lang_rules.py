#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Language-rule cache backed by the ``languages`` DB table.

Each row in the table controls how articles written in a given language are
translated:
  translate=0  → no translation needed (en, pt, pt-BR, …)
  translate=1  → translate to ``translate_to`` ('pt' for Romance, 'en' otherwise)
  translator_code → deep-translator compatible source code (e.g. zh-CN, iw)
"""

import sqlite3
from functools import lru_cache

DB_PATH = "predator_news.db"

# Default target language when the source is unknown / undetectable.
AUTO_FALLBACK_TARGET = "en"


@lru_cache(maxsize=1)
def _load_language_rules() -> dict:
    """
    Load all rows from the ``languages`` table into a dict.

    Returns: ``{ language_code: {'translate': bool, 'translate_to': str,
                                  'translator_code': str} }``

    The result is cached after the first call; call
    ``_load_language_rules.cache_clear()`` to force a reload.
    """
    rules: dict = {}
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("""
            SELECT language_code, translator_code, translate, translate_to,
                   translate_backend, translate_without_enrichment
            FROM languages
        """)
        for row in cur.fetchall():
            rules[row['language_code']] = {
                'translate': bool(row['translate']),
                'translate_to': row['translate_to'],
                'translator_code': row['translator_code'] or row['language_code'],
                'translate_backend': row['translate_backend'] or 'nllb',
                'translate_without_enrichment': bool(row['translate_without_enrichment']),
            }
        con.close()
    except Exception as e:
        print(f"[lang_rules] Warning: could not load language rules: {e}")
    return rules


def get_language_rules(language_code: str) -> dict | None:
    """Return the translation rule for *language_code*, or ``None`` if unknown."""
    return _load_language_rules().get(language_code)


# Warm the cache synchronously at import time so the first call from an
# async context never opens a sqlite3 connection on the event loop thread.
try:
    _load_language_rules()
except Exception:
    pass
