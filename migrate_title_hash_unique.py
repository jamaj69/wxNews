#!/usr/bin/env python3
"""
One-time migration:
  1. Backfill title_hash for all articles that have NULL/empty title_hash.
  2. Remove duplicate rows — keep the earliest inserted (lowest rowid) per hash.
  3. Drop the old non-unique index and create a UNIQUE partial index.

Run with the service stopped:
    sudo systemctl stop wxAsyncNewsGather.service
    python3 migrate_title_hash_unique.py
    sudo systemctl start wxAsyncNewsGather.service
"""

import hashlib
import sqlite3
import sys
import time

DB_PATH = "predator_news.db"
BATCH_SIZE = 10_000


def make_title_hash(title: str | None) -> str | None:
    """Mirrors _make_title_hash() in wxAsyncNewsGather.py. Returns None for blank titles."""
    if not title or not title.strip():
        return None
    norm = ' '.join(title.lower().split())
    return hashlib.sha1(norm.encode('utf-8', errors='ignore')).hexdigest()[:16]


def main() -> None:
    print(f"Opening {DB_PATH} ...")
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit off via BEGIN
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-131072")  # 128 MB page cache

    # ── Step 1: Backfill ─────────────────────────────────────────────────────
    total = conn.execute(
        "SELECT COUNT(*) FROM gm_articles WHERE title_hash IS NULL OR title_hash = ''"
    ).fetchone()[0]
    print(f"Step 1: Backfilling {total:,} articles with missing title_hash ...")

    updated = 0
    t0 = time.time()
    while True:
        rows = conn.execute(
            "SELECT rowid, title FROM gm_articles "
            "WHERE title_hash IS NULL OR title_hash = '' "
            "LIMIT ?",
            (BATCH_SIZE,),
        ).fetchall()
        if not rows:
            break

        updates = [(make_title_hash(title), rowid) for rowid, title in rows]
        conn.execute("BEGIN")
        conn.executemany(
            "UPDATE gm_articles SET title_hash = ? WHERE rowid = ?", updates
        )
        conn.execute("COMMIT")

        updated += len(rows)
        elapsed = time.time() - t0
        rate = updated / elapsed if elapsed > 0 else 0
        print(f"  {updated:,}/{total:,} ({rate:,.0f} rows/s)", end='\r', flush=True)

    print(f"\n  ✅ Backfill complete — {updated:,} rows updated in {time.time()-t0:.1f}s.")

    # ── Step 2: Remove duplicates ─────────────────────────────────────────────
    print("Step 2: Counting duplicate title_hashes ...")
    dupe_count = conn.execute("""
        SELECT COUNT(*) FROM gm_articles
        WHERE title_hash IS NOT NULL AND title_hash != ''
          AND rowid NOT IN (
              SELECT MIN(rowid) FROM gm_articles
              WHERE title_hash IS NOT NULL AND title_hash != ''
              GROUP BY title_hash
          )
    """).fetchone()[0]
    print(f"  Found {dupe_count:,} duplicate rows.")

    if dupe_count > 0:
        print(f"  Deleting {dupe_count:,} duplicates (keeping earliest rowid per hash) ...")
        conn.execute("BEGIN")
        conn.execute("""
            DELETE FROM gm_articles
            WHERE title_hash IS NOT NULL AND title_hash != ''
              AND rowid NOT IN (
                  SELECT MIN(rowid) FROM gm_articles
                  WHERE title_hash IS NOT NULL AND title_hash != ''
                  GROUP BY title_hash
              )
        """)
        conn.execute("COMMIT")
        print(f"  ✅ {dupe_count:,} duplicates removed.")

    # ── Step 3: Replace index ─────────────────────────────────────────────────
    print("Step 3: Replacing idx_articles_title_hash with UNIQUE version ...")
    conn.execute("BEGIN")
    conn.execute("DROP INDEX IF EXISTS idx_articles_title_hash")
    conn.execute("""
        CREATE UNIQUE INDEX idx_articles_title_hash
        ON gm_articles(title_hash)
    """)
    conn.execute("COMMIT")
    print("  ✅ UNIQUE index created.")

    conn.close()
    print("\nMigration complete. You can now restart the service.")


if __name__ == "__main__":
    main()
