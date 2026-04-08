#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect_source_languages.py

Two-phase script:

Phase 1 — Analyze article language distribution per source:
  For each source that has detected articles, count how many articles are in
  each language.  If >= MIN_CONFIDENCE_PCT% of the articles with a detected
  language share the same language, that source is considered mono-lingual
  and its `language` column in gm_sources is updated.

Phase 2 — Back-fill missing detected_language in articles:
  For every article whose detected_language IS NULL, if its source has a
  resolved language in gm_sources, set the article's detected_language to
  that language.

Usage:
    python3 detect_source_languages.py [--dry-run] [--min-pct 80] [--min-articles 5]
"""

import argparse
import sqlite3
import sys
from collections import Counter

DB_PATH = "predator_news.db"

# Minimum % of same-language articles needed to call a source mono-lingual
DEFAULT_MIN_PCT = 80
# Minimum number of articles with detected language to make a decision
DEFAULT_MIN_ARTICLES = 5


def load_source_language_stats(cur: sqlite3.Cursor) -> dict:
    """
    Returns a dict keyed by id_source:
        {
            'total_articles': int,
            'articles_with_lang': int,
            'lang_counts': Counter,          # {lang: count}
            'dominant_lang': str | None,
            'dominant_pct': float,
            'current_language': str | None,  # what gm_sources.language says now
        }
    """
    # Fetch all (id_source, detected_language) pairs in one query
    cur.execute("""
        SELECT a.id_source,
               a.detected_language,
               COUNT(*) AS cnt
        FROM gm_articles a
        GROUP BY a.id_source, a.detected_language
    """)
    rows = cur.fetchall()

    # Fetch current language values from gm_sources
    cur.execute("SELECT id_source, language FROM gm_sources")
    src_lang = {r["id_source"]: r["language"] for r in cur.fetchall()}

    stats: dict = {}
    for row in rows:
        sid   = row["id_source"]
        lang  = row["detected_language"]   # may be None
        cnt   = row["cnt"]
        if sid not in stats:
            stats[sid] = {
                "total_articles": 0,
                "articles_with_lang": 0,
                "lang_counts": Counter(),
                "dominant_lang": None,
                "dominant_pct": 0.0,
                "current_language": src_lang.get(sid),
            }
        stats[sid]["total_articles"] += cnt
        if lang:
            stats[sid]["articles_with_lang"] += cnt
            stats[sid]["lang_counts"][lang] += cnt

    # Compute dominant language per source
    for sid, d in stats.items():
        if d["articles_with_lang"] > 0:
            top_lang, top_cnt = d["lang_counts"].most_common(1)[0]
            pct = top_cnt / d["articles_with_lang"] * 100
            d["dominant_lang"] = top_lang
            d["dominant_pct"] = round(pct, 1)

    return stats


def phase1_update_sources(
    cur: sqlite3.Cursor,
    stats: dict,
    min_pct: float,
    min_articles: int,
    dry_run: bool,
) -> tuple[int, int, int]:
    """
    Update gm_sources.language where a mono-lingual source is identified.

    Returns (updated, skipped_low_confidence, skipped_multilingual)
    """
    updated = 0
    skipped_low = 0
    skipped_multi = 0

    for sid, d in stats.items():
        if d["articles_with_lang"] < min_articles:
            skipped_low += 1
            continue

        if d["dominant_pct"] < min_pct:
            skipped_multi += 1
            continue

        lang = d["dominant_lang"]
        current = d["current_language"]

        if current == lang:
            # Already up to date
            continue

        updated += 1
        print(
            f"  {'[DRY]' if dry_run else '[UPD]'} {sid}: "
            f"{current!r} → {lang!r}  "
            f"({d['dominant_pct']}% of {d['articles_with_lang']} articles)"
        )
        if not dry_run:
            cur.execute(
                "UPDATE gm_sources SET language = ? WHERE id_source = ?",
                (lang, sid),
            )

    return updated, skipped_low, skipped_multi


def phase2_backfill_articles(
    cur: sqlite3.Cursor,
    dry_run: bool,
) -> int:
    """
    For articles with detected_language IS NULL, use their source's language.
    Returns number of articles updated.
    """
    if dry_run:
        cur.execute("""
            SELECT COUNT(*)
            FROM gm_articles a
            JOIN gm_sources s ON a.id_source = s.id_source
            WHERE a.detected_language IS NULL
              AND s.language IS NOT NULL
              AND s.language != ''
        """)
        count = cur.fetchone()[0]
        print(f"  [DRY] Would back-fill detected_language for {count:,} articles")
        return count

    cur.execute("""
        UPDATE gm_articles
        SET detected_language = (
            SELECT s.language
            FROM gm_sources s
            WHERE s.id_source = gm_articles.id_source
              AND s.language IS NOT NULL
              AND s.language != ''
        )
        WHERE detected_language IS NULL
          AND id_source IN (
              SELECT id_source FROM gm_sources
              WHERE language IS NOT NULL AND language != ''
          )
    """)
    return cur.rowcount


def phase3_mark_no_translate(cur: sqlite3.Cursor, dry_run: bool) -> int:
    """
    After back-filling detected_language, mark articles in non-translatable
    languages (translate=0) that were still is_translated=0 as is_translated=-1.
    Returns number of articles updated.
    """
    if dry_run:
        cur.execute("""
            SELECT COUNT(*)
            FROM gm_articles
            WHERE is_translated = 0
              AND detected_language IN (
                  SELECT language_code FROM languages WHERE translate = 0
              )
        """)
        count = cur.fetchone()[0]
        print(f"  [DRY] Would mark {count:,} articles as is_translated=-1 (no translation needed)")
        return count

    cur.execute("""
        UPDATE gm_articles
        SET is_translated = -1
        WHERE is_translated = 0
          AND detected_language IN (
              SELECT language_code FROM languages WHERE translate = 0
          )
    """)
    return cur.rowcount


def print_multilingual_sources(stats: dict, min_articles: int, top_n: int = 20):
    """Print sources that are genuinely multi-lingual (might need special handling)."""
    multi = [
        (sid, d)
        for sid, d in stats.items()
        if d["articles_with_lang"] >= min_articles and d["dominant_pct"] < 80
    ]
    multi.sort(key=lambda x: x[1]["articles_with_lang"], reverse=True)
    if not multi:
        print("  (none found)")
        return
    for sid, d in multi[:top_n]:
        top3 = d["lang_counts"].most_common(3)
        langs_str = ", ".join(f"{l}={c}" for l, c in top3)
        print(f"  {sid}: {d['articles_with_lang']} articles — {langs_str}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without changing the DB")
    parser.add_argument("--min-pct", type=float, default=DEFAULT_MIN_PCT,
                        help=f"Minimum %% of same-language articles to call a source mono-lingual (default: {DEFAULT_MIN_PCT})")
    parser.add_argument("--min-articles", type=int, default=DEFAULT_MIN_ARTICLES,
                        help=f"Minimum articles with detected language per source (default: {DEFAULT_MIN_ARTICLES})")
    parser.add_argument("--show-multilingual", action="store_true",
                        help="Print list of sources with mixed languages")
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # ── Phase 1 ───────────────────────────────────────────────────────────────
    print("=" * 65)
    print("Phase 1: Analyzing article language distribution per source...")
    print("=" * 65)
    stats = load_source_language_stats(cur)
    print(f"  Sources with articles: {len(stats):,}")
    sources_with_data = sum(1 for d in stats.values() if d["articles_with_lang"] >= args.min_articles)
    print(f"  Sources with >= {args.min_articles} language-detected articles: {sources_with_data:,}")

    if args.show_multilingual:
        print()
        print(f"Multi-lingual sources (dominant language < 80%):")
        print_multilingual_sources(stats, args.min_articles)

    print()
    print(f"Updating gm_sources.language (min_pct={args.min_pct}%, min_articles={args.min_articles}):")
    updated, skipped_low, skipped_multi = phase1_update_sources(
        cur, stats, args.min_pct, args.min_articles, args.dry_run
    )
    print()
    print(f"  Sources updated:              {updated:,}")
    print(f"  Skipped (not enough data):    {skipped_low:,}")
    print(f"  Skipped (multi-lingual):      {skipped_multi:,}")

    if not args.dry_run:
        con.commit()

    # ── Phase 2 ───────────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("Phase 2: Back-filling missing detected_language in articles...")
    print("=" * 65)
    backfilled = phase2_backfill_articles(cur, args.dry_run)
    if not args.dry_run:
        con.commit()
        print(f"  Articles back-filled: {backfilled:,}")

    # ── Phase 3 ───────────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("Phase 3: Marking newly-identified non-translatable articles...")
    print("=" * 65)
    marked = phase3_mark_no_translate(cur, args.dry_run)
    if not args.dry_run:
        con.commit()
        print(f"  Articles marked is_translated=-1: {marked:,}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("Summary after all phases:")
    print("=" * 65)
    cur.execute("SELECT COUNT(*) FROM gm_articles WHERE is_translated = 0 AND title IS NOT NULL AND title != ''")
    pending = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM gm_articles WHERE detected_language IS NULL")
    still_null = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM gm_articles WHERE is_translated = 1")
    done = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM gm_articles WHERE is_translated = -1")
    skipped = cur.fetchone()[0]
    print(f"  Pending translation (is_translated=0): {pending:,}")
    print(f"  Translated (is_translated=1):          {done:,}")
    print(f"  Skipped (is_translated=-1):            {skipped:,}")
    print(f"  Articles with no language detected:    {still_null:,}")

    con.close()
    print()
    print("Done." if not args.dry_run else "Dry-run complete — no changes were committed.")


if __name__ == "__main__":
    main()
