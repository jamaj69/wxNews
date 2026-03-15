#!/usr/bin/env python3
"""
Remove truncated articles from database so they can be re-collected with full content.
Identifies articles with:
- Descriptions exactly 500 characters (old truncation limit)
- Descriptions ending with incomplete text
"""

import sqlite3
import sys
from decouple import config
import os

def dbCredentials():
    """Return SQLite database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path

def find_truncated_articles(conn):
    """Find articles that appear to be truncated"""
    cursor = conn.cursor()
    
    # Find articles with:
    # 1. Description exactly 500 chars (old limit)
    # 2. Description or content ending mid-sentence
    query = """
    SELECT 
        id_article, 
        title,
        LENGTH(description) as desc_len,
        SUBSTR(description, -50, 50) as desc_end,
        id_source,
        published_at_gmt
    FROM gm_articles 
    WHERE 
        LENGTH(description) = 500
        OR description LIKE '%</a'
        OR description LIKE '%</p'
        OR description LIKE '%<img%'
    ORDER BY published_at_gmt DESC
    """
    
    cursor.execute(query)
    return cursor.fetchall()

def main():
    db_path = dbCredentials()
    print(f"📊 Connecting to database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    
    try:
        # Find truncated articles
        truncated = find_truncated_articles(conn)
        
        if not truncated:
            print("✅ No truncated articles found!")
            return 0
        
        print(f"\n🔍 Found {len(truncated)} potentially truncated articles:\n")
        
        # Display sample
        for i, article in enumerate(truncated[:10], 1):
            article_id, title, desc_len, desc_end, source_id, published = article
            print(f"{i}. [{source_id}] {title[:60]}...")
            print(f"   Length: {desc_len} chars")
            print(f"   Ends with: ...{desc_end}")
            print()
        
        if len(truncated) > 10:
            print(f"   ... and {len(truncated) - 10} more\n")
        
        # Confirm deletion
        response = input(f"\n⚠️  Delete these {len(truncated)} truncated articles? [y/N]: ").strip().lower()
        
        if response != 'y':
            print("❌ Cancelled")
            return 1
        
        # Delete truncated articles
        article_ids = [article[0] for article in truncated]
        placeholders = ','.join('?' * len(article_ids))
        delete_query = f"DELETE FROM gm_articles WHERE id_article IN ({placeholders})"
        
        cursor = conn.cursor()
        cursor.execute(delete_query, article_ids)
        conn.commit()
        
        deleted_count = cursor.rowcount
        print(f"\n✅ Deleted {deleted_count} truncated articles")
        print(f"📥 These articles will be re-collected with full content on next collection cycle")
        
        # Show affected sources
        cursor.execute("""
            SELECT DISTINCT s.name, COUNT(*) as count
            FROM gm_sources s
            WHERE s.id_source IN (
                SELECT DISTINCT id_source FROM (
                    SELECT id_source FROM gm_articles WHERE 0
                )
            )
        """)
        
        print("\n📌 Affected sources will be re-collected in the next cycle (15-60 minutes)")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()

if __name__ == '__main__':
    sys.exit(main())
