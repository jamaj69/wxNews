#!/usr/bin/env python3
"""
Check which sources are blocklisted in the database.
"""

import sqlite3
import os

def check_blocklist():
    db_path = os.path.join(os.path.dirname(__file__), 'predator_news.db')
    
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if columns exist
    try:
        cursor.execute("SELECT fetch_blocked, blocked_count FROM gm_sources LIMIT 1")
    except sqlite3.OperationalError as e:
        print(f"Blocklist columns not yet added to database: {e}")
        print("They will be added automatically when the service starts.")
        conn.close()
        return
    
    # Get blocked sources
    cursor.execute("""
        SELECT id_source, name, url, blocked_count, fetch_blocked
        FROM gm_sources
        WHERE fetch_blocked = 1 OR blocked_count > 0
        ORDER BY blocked_count DESC
    """)
    
    blocked = cursor.fetchall()
    
    if not blocked:
        print("✅ No sources are currently blocklisted")
    else:
        print(f"\n🚫 Blocklisted Sources ({len(blocked)}):")
        print("=" * 80)
        for source_id, name, url, count, is_blocked in blocked:
            status = "🚫 BLOCKED" if is_blocked else f"⚠️  {count} errors"
            print(f"{status:15} {name[:40]:40} ({count} 403s)")
            if url:
                print(f"               URL: {url}")
            print()
    
    # Get total sources count
    cursor.execute("SELECT COUNT(*) FROM gm_sources")
    total = cursor.fetchone()[0]
    
    blocked_count = len([s for s in blocked if s[4] == 1])
    warning_count = len([s for s in blocked if s[4] == 0])
    
    print("=" * 80)
    print(f"Summary: {blocked_count} blocked, {warning_count} with errors, {total} total sources")
    
    conn.close()

if __name__ == '__main__':
    check_blocklist()
