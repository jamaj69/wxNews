#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
redetect_article_languages.py

Re-verifies the detected_language of pending articles (is_translated=0) using
langdetect. When the re-detected language differs AND doesn't need translation
(e.g. article was marked 'cy' but is really 'en'), corrects:

  1. gm_articles.detected_language  → real language
  2. gm_articles.is_translated      → -1 (no translation needed)
  3. gm_sources.language            → updated if >= MIN_SOURCE_PCT% of that
                                       source's pending articles were corrected
                                       to the same language.

Usage:
    python3 redetect_article_languages.py [--dry-run] [--batch 500]
"""

import argparse
import re
import sqlite3
from collections import Counter, defaultdict

from langdetect import detect, LangDetectException

DB_PATH = "predator_news.db"

# Minimum characters to run langdetect (too short = unreliable)
MIN_TEXT_LEN = 30
# Minimum % of corrected articles pointing to the same language to update a source
MIN_SOURCE_PCT = 80
# Minimum corrected articles per source to consider updating it
MIN_SOURCE_ARTICLES = 5


def strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def load_no_translate_langs(cur: sqlite3.Cursor) -> set:
    """Return set of language codes that don't need translation (translate=0)."""
    cur.execute("SELECT language_code FROM languages WHERE translate = 0")
    return {r[0] for r in cur.fetchall()}


def redetect(text: str) -> str | None:
    """Return detected language code, or None on failure."""
    clean = strip_html(text or '')
    if len(clean) < MIN_TEXT_LEN:
        return None
    try:
        return detect(clean[:2000])
    except LangDetectException:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be changed without modifying the DB')
    parser.add_argument('--batch', type=int, default=0,
                        help='Limit number of articles to process (0 = all)')
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    no_translate = load_no_translate_langs(cur)
    print(f"Languages that don't need translation: {sorted(no_translate)}")
    print()

    # Fetch pending articles
    limit_clause = f"LIMIT {args.batch}" if args.batch > 0 else ""
    cur.execute(f"""
        SELECT id_article, id_source, detected_language, title, description, content
        FROM gm_articles
        WHERE is_translated = 0
          AND title IS NOT NULL AND title != ''
        ORDER BY inserted_at_ms DESC
        {limit_clause}
    """)
    articles = cur.fetchall()
    print(f"Articles to check: {len(articles):,}")
    print()

    corrected = 0
    unchanged = 0
    skipped = 0

    # Track corrections per source: {id_source: Counter({new_lang: count})}
    source_corrections: dict = defaultdict(Counter)

    for art in articles:
        art_id       = art['id_article']
        src_id       = art['id_source']
        orig_lang    = art['detected_language']
        title        = art['title'] or ''
        description  = art['description'] or ''
        content      = art['content'] or ''

        # Build detection text: title + description (content may be empty)
        text = f"{title}. {description}" if description else title

        new_lang = redetect(text)
        if new_lang is None:
            skipped += 1
            continue

        # Normalize: langdetect returns 'zh-cn'/'zh-tw', map to 'zh'
        if new_lang.startswith('zh'):
            new_lang = 'zh'

        if new_lang == orig_lang:
            unchanged += 1
            continue

        # Only act if the newly detected language doesn't need translation
        if new_lang not in no_translate:
            unchanged += 1
            continue

        # Re-detection changed AND new lang is no-translate → correct it
        corrected += 1
        source_corrections[src_id][new_lang] += 1

        print(f"  {'[DRY]' if args.dry_run else '[FIX]'} "
              f"{art_id[:40]}  {orig_lang!r} → {new_lang!r}  {title[:60]}")

        if not args.dry_run:
            cur.execute("""
                UPDATE gm_articles
                SET detected_language = ?, is_translated = -1
                WHERE id_article = ?
            """, (new_lang, art_id))

    if not args.dry_run:
        con.commit()

    print()
    print("=" * 60)
    print(f"Articles corrected:  {corrected:,}")
    print(f"Articles unchanged:  {unchanged:,}")
    print(f"Articles skipped:    {skipped:,}  (text too short for detection)")
    print()

    # ── Update sources ────────────────────────────────────────────────────────
    print("Source updates:")
    sources_updated = 0
    for src_id, lang_counts in source_corrections.items():
        total = sum(lang_counts.values())
        if total < MIN_SOURCE_ARTICLES:
            continue
        top_lang, top_cnt = lang_counts.most_common(1)[0]
        pct = top_cnt / total * 100
        if pct < MIN_SOURCE_PCT:
            continue

        # Fetch current source language
        cur.execute("SELECT language, name FROM gm_sources WHERE id_source = ?", (src_id,))
        row = cur.fetchone()
        if not row:
            continue
        current_lang = row['language']
        src_name     = row['name'] or src_id

        if current_lang == top_lang:
            continue

        sources_updated += 1
        print(f"  {'[DRY]' if args.dry_run else '[UPD]'} {src_name}: "
              f"{current_lang!r} → {top_lang!r}  ({pct:.0f}% of {total} corrected)")

        if not args.dry_run:
            cur.execute("UPDATE gm_sources SET language = ? WHERE id_source = ?",
                        (top_lang, src_id))

    if not args.dry_run:
        con.commit()

    print()
    print(f"Sources updated: {sources_updated:,}")

    # ── Final summary ─────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    cur.execute("""
        SELECT COUNT(*) FROM gm_articles
        WHERE is_translated = 0 AND title IS NOT NULL AND title != ''
    """)
    pending = cur.fetchone()[0]
    print(f"Pending translation queue now: {pending:,}")

    con.close()
    print()
    print("Done." if not args.dry_run else "Dry-run complete — no changes committed.")


if __name__ == '__main__':
    main()
