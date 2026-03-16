#!/usr/bin/env python3
"""
Add inserted_at_ms timestamp column to gm_articles table
"""

import sqlite3
import os
from decouple import config

def get_db_path():
    """Get database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path

def main():
    db_path = get_db_path()
    print(f"📊 Connecting to database: {db_path}\n")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(gm_articles)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'inserted_at_ms' in columns:
            print("✅ Column 'inserted_at_ms' already exists")
        else:
            print("📝 Adding column 'inserted_at_ms'...")
            cursor.execute("""
                ALTER TABLE gm_articles 
                ADD COLUMN inserted_at_ms INTEGER
            """)
            print("✅ Column added successfully")
        
        # Create index
        print("\n📊 Creating index on inserted_at_ms...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_articles_inserted_ms 
            ON gm_articles(inserted_at_ms DESC)
        """)
        print("✅ Index created successfully")
        
        # Backfill existing articles with approximate timestamps
        print("\n⏱️  Backfilling timestamps for existing articles...")
        cursor.execute("""
            UPDATE gm_articles 
            SET inserted_at_ms = CAST((julianday(published_at_gmt) - julianday('1970-01-01')) * 86400000 AS INTEGER)
            WHERE inserted_at_ms IS NULL 
            AND published_at_gmt IS NOT NULL
        """)
        updated = cursor.rowcount
        print(f"✅ Backfilled {updated:,} articles with timestamps from published_at_gmt")
        
        # For articles without published_at_gmt, use a default old timestamp
        cursor.execute("""
            UPDATE gm_articles 
            SET inserted_at_ms = 0
            WHERE inserted_at_ms IS NULL
        """)
        updated = cursor.rowcount
        if updated > 0:
            print(f"✅ Set default timestamp for {updated:,} articles without dates")
        
        conn.commit()
        
        # Verify
        print("\n📊 Verification:")
        cursor.execute("SELECT COUNT(*) FROM gm_articles WHERE inserted_at_ms IS NULL")
        null_count = cursor.fetchone()[0]
        print(f"   Articles with NULL timestamp: {null_count}")
        
        cursor.execute("""
            SELECT COUNT(*), 
                   MIN(inserted_at_ms), 
                   MAX(inserted_at_ms) 
            FROM gm_articles 
            WHERE inserted_at_ms > 0
        """)
        total, min_ts, max_ts = cursor.fetchone()
        print(f"   Articles with timestamp: {total:,}")
        print(f"   Oldest timestamp: {min_ts} ({min_ts // 1000})")
        print(f"   Newest timestamp: {max_ts} ({max_ts // 1000})")
        
        print("\n✅ Migration complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
        return 1
    finally:
        conn.close()
    
    return 0

if __name__ == '__main__':
    exit(main())
