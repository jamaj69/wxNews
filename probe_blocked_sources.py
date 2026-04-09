#!/usr/bin/env python3
"""
probe_blocked_sources.py — Test-fetch blocked sources and auto-unblock those
that respond successfully.

Usage:
    python probe_blocked_sources.py [--dry-run] [--max-count N] [--name PATTERN]

Options:
    --dry-run        Report what would be unblocked without writing to DB.
    --max-count N    Only probe sources with blocked_count <= N (default: all).
    --min-count N    Only probe sources with blocked_count >= N (default: 3).
    --name PATTERN   Filter source names (case-insensitive substring).

Strategy:
    For each blocked source, the most recent article URL is fetched.
    - SUCCESS → reset fetch_blocked=0, blocked_count=0 (source is alive again).
    - FAILURE → leave blocked, report the error code.

This is safe to run while the service is running (SQLite WAL mode).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from typing import Optional

from article_fetcher import fetch_article_content
from decouple import config

DB_PATH = str(config('DB_PATH', default='predator_news.db'))
PROBE_TIMEOUT = 15   # generous timeout for probe attempt


def probe_source(source_id: str, source_name: str, url: str) -> tuple[bool, Optional[int]]:
    """
    Fetch one URL from a blocked source.

    Returns:
        (success: bool, error_code: int | None)
    """
    result = fetch_article_content(url, PROBE_TIMEOUT)
    if result and result.get('success'):
        return True, None
    error_code = result.get('error_code') if result else None
    return False, error_code


def run(
    dry_run: bool = False,
    max_count: Optional[int] = None,
    min_count: int = 3,
    name_pattern: Optional[str] = None,
) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ── Build query ────────────────────────────────────────────────────────
    where_clauses = ["s.fetch_blocked = 1"]
    params: list = []

    if min_count is not None:
        where_clauses.append("s.blocked_count >= ?")
        params.append(min_count)
    if max_count is not None:
        where_clauses.append("s.blocked_count <= ?")
        params.append(max_count)
    if name_pattern:
        where_clauses.append("LOWER(s.name) LIKE LOWER(?)")
        params.append(f'%{name_pattern}%')

    where = ' AND '.join(where_clauses)

    rows = conn.execute(f"""
        SELECT s.id_source, s.name, s.blocked_count,
               a.url AS sample_url
        FROM gm_sources s
        JOIN gm_articles a ON a.id_source = s.id_source
          AND a.id_article = (
            SELECT MAX(id_article)
            FROM gm_articles
            WHERE id_source = s.id_source
              AND url IS NOT NULL AND url != ''
          )
        WHERE {where}
        ORDER BY s.blocked_count ASC, s.name
    """, params).fetchall()

    if not rows:
        print("✅ No blocked sources match the criteria.")
        conn.close()
        return

    print(f"\n🔍 Probing {len(rows)} blocked source(s)"
          f"{' [DRY RUN]' if dry_run else ''}…")
    print("=" * 90)

    unblocked = []
    still_blocked = []

    for row in rows:
        source_id   = row['id_source']
        source_name = row['name'] or source_id
        count       = row['blocked_count']
        url         = row['sample_url']

        print(f"\n  [{count:3d} errors] {source_name}")
        print(f"             URL: {url}")

        success, error_code = probe_source(source_id, source_name, url)

        if success:
            print(f"  ✅ SUCCESS — source is alive!")
            unblocked.append((source_id, source_name, count))
            if not dry_run:
                cur = conn.execute("""
                    UPDATE gm_sources
                    SET fetch_blocked = 0,
                        blocked_count = 0
                    WHERE id_source = ?
                """, (source_id,))
                reset = conn.execute("""
                    UPDATE gm_articles
                    SET is_enriched = 0
                    WHERE id_source = ?
                      AND is_enriched != 1
                """, (source_id,))
                conn.commit()
                print(f"             ↩  {reset.rowcount} article(s) reset to pending enrichment.")
        else:
            label = f"HTTP {error_code}" if error_code else "no data / timeout"
            print(f"  🚫 STILL BLOCKED — {label}")
            still_blocked.append((source_id, source_name, count, error_code))

        # Be polite between probes
        time.sleep(1)

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print(f"\n📊 Summary{' [DRY RUN]' if dry_run else ''}:")
    print(f"   Probed:       {len(rows)}")
    print(f"   ✅ Unblocked: {len(unblocked)}")
    print(f"   🚫 Still blocked: {len(still_blocked)}")

    if unblocked:
        print("\n  Unblocked sources:")
        for sid, name, cnt in unblocked:
            action = "(would unblock)" if dry_run else "(unblocked ✅)"
            print(f"    • {name}  [was {cnt} errors]  {action}")

    if still_blocked:
        print("\n  Still blocked sources:")
        for sid, name, cnt, ec in still_blocked:
            label = f"HTTP {ec}" if ec else "no data"
            print(f"    • {name}  [{cnt} errors, {label}]")

    conn.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='Report only, do not write to DB.')
    ap.add_argument('--max-count', type=int, default=None,
                    help='Only probe sources with blocked_count <= N.')
    ap.add_argument('--min-count', type=int, default=3,
                    help='Only probe sources with blocked_count >= N (default 3).')
    ap.add_argument('--name', default=None,
                    help='Filter by source name substring (case-insensitive).')
    args = ap.parse_args()

    run(
        dry_run=args.dry_run,
        max_count=args.max_count,
        min_count=args.min_count,
        name_pattern=args.name,
    )
