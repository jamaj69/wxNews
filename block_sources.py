#!/usr/bin/env python3
"""
Manually block/unblock RSS sources in the database.
"""

import sqlite3
import sys
from typing import List

DB_PATH = 'predator_news.db'

def block_sources(source_names: List[str], should_block: bool = True):
    """
    Block or unblock sources by name.
    
    Args:
        source_names: List of source names to block/unblock
        should_block: True to block, False to unblock
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    action = "BLOCKING" if should_block else "UNBLOCKING"
    blocked_val = 1 if should_block else 0
    
    print(f"\n{action} sources...")
    print("=" * 80)
    
    for name in source_names:
        # Find sources by name (case-insensitive, partial match)
        cursor.execute("""
            SELECT id_source, name, url
            FROM gm_sources
            WHERE LOWER(name) LIKE LOWER(?)
        """, (f'%{name}%',))
        
        results = cursor.fetchall()
        
        if not results:
            print(f"❌ Not found: {name}")
            continue
        
        for source_id, source_name, url in results:
            cursor.execute("""
                UPDATE gm_sources
                SET fetch_blocked = ?, blocked_count = 3
                WHERE id_source = ?
            """, (blocked_val, source_id))
            
            status = "🚫 BLOCKED" if should_block else "✅ UNBLOCKED"
            print(f"{status}: {source_name}")
            if url:
                print(f"         {url}")
    
    conn.commit()
    print("=" * 80)
    print(f"✅ Changes saved to database")
    conn.close()


def list_problematic_sources():
    """Show sources with errors but not yet blocked."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id_source, name, url, blocked_count, fetch_blocked
        FROM gm_sources
        WHERE blocked_count > 0 AND fetch_blocked = 0
        ORDER BY blocked_count DESC
    """)
    
    sources = cursor.fetchall()
    
    if not sources:
        print("✅ No sources with partial errors (all clean or blocked)")
    else:
        print(f"\n⚠️  Sources with errors but not yet blocked ({len(sources)}):")
        print("=" * 80)
        for source_id, name, url, count, _ in sources:
            print(f"⚠️  {count} errors: {name}")
            if url:
                print(f"          {url}")
            print()
    
    conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("""
Usage:
  python3 block_sources.py list                    # List sources with errors
  python3 block_sources.py block <name1> <name2>   # Block sources
  python3 block_sources.py unblock <name1> <name2> # Unblock sources

Examples:
  python3 block_sources.py list
  python3 block_sources.py block "TecnoGaming" "Computer Hoy" "Alt1040"
  python3 block_sources.py unblock "BBC" "CNN"
        """)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'list':
        list_problematic_sources()
    elif command == 'block':
        if len(sys.argv) < 3:
            print("❌ Please provide source names to block")
            sys.exit(1)
        block_sources(sys.argv[2:], should_block=True)
    elif command == 'unblock':
        if len(sys.argv) < 3:
            print("❌ Please provide source names to unblock")
            sys.exit(1)
        block_sources(sys.argv[2:], should_block=False)
    else:
        print(f"❌ Unknown command: {command}")
        print("Use: list, block, or unblock")
        sys.exit(1)
