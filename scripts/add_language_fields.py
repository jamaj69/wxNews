#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Add language detection and translation fields to gm_articles table
"""

import sqlite3
import os
from decouple import config

def get_db_path():
    """Get database path from environment or default"""
    db_path = str(config('DB_PATH', default='predator_news.db', cast=str))
    if not os.path.isabs(db_path):
        # Get project root (parent of scripts directory if running from scripts/)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.basename(script_dir) == 'scripts':
            project_root = os.path.dirname(script_dir)
        else:
            project_root = script_dir
        db_path = os.path.join(project_root, db_path)
    return db_path


def add_language_columns():
    """Add language detection and translation columns to gm_articles"""
    db_path = get_db_path()
    print(f"📊 Connecting to database: {db_path}\n")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check existing columns
        cursor.execute("PRAGMA table_info(gm_articles)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"📋 Current columns: {', '.join(columns)}\n")
        
        columns_to_add = [
            ('detected_language', 'TEXT', 'Language code (en, pt, es, etc.)'),
            ('language_confidence', 'REAL', 'Detection confidence (0.0 to 1.0)'),
            ('translated_title', 'TEXT', 'Translated article title'),
            ('translated_description', 'TEXT', 'Translated article description'),
            ('translated_content', 'TEXT', 'Translated article content'),
        ]
        
        for col_name, col_type, description in columns_to_add:
            if col_name in columns:
                print(f"✅ Column '{col_name}' already exists")
            else:
                print(f"📝 Adding column '{col_name}' ({description})...")
                cursor.execute(f"""
                    ALTER TABLE gm_articles 
                    ADD COLUMN {col_name} {col_type}
                """)
                print(f"✅ Column '{col_name}' added successfully")
        
        # Create indexes for efficient language filtering
        print("\n📊 Creating indexes...")
        
        index_queries = [
            ('idx_articles_language', 'detected_language', 'Fast language filtering'),
            ('idx_articles_lang_confidence', 'language_confidence DESC', 'Sort by detection confidence'),
        ]
        
        for idx_name, idx_column, description in index_queries:
            try:
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS {idx_name} 
                    ON gm_articles({idx_column})
                """)
                print(f"✅ Index '{idx_name}' created - {description}")
            except sqlite3.OperationalError as e:
                if 'already exists' in str(e):
                    print(f"✅ Index '{idx_name}' already exists")
                else:
                    raise
        
        conn.commit()
        
        # Show updated schema
        print("\n" + "="*70)
        print("UPDATED SCHEMA")
        print("="*70)
        cursor.execute("PRAGMA table_info(gm_articles)")
        for row in cursor.fetchall():
            col_id, name, col_type, notnull, default, pk = row
            print(f"{col_id:2d}. {name:25s} {col_type:10s} {'PRIMARY KEY' if pk else ''}")
        
        # Show indexes
        print("\n" + "="*70)
        print("INDEXES")
        print("="*70)
        cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='gm_articles'")
        for idx_name, idx_sql in cursor.fetchall():
            if idx_name.startswith('idx_'):  # Only show our custom indexes
                print(f"📊 {idx_name}")
                print(f"   {idx_sql}")
        
        print("\n✨ Database schema updated successfully!")
        print("\n💡 Next steps:")
        print("   1. Install language detection: pip install langdetect")
        print("   2. Install translation: pip install googletrans==4.0.0rc1")
        print("   3. Use language_service.py to detect and translate articles")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error updating schema: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


def show_language_stats():
    """Show statistics about detected languages in articles"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("\n" + "="*70)
    print("LANGUAGE STATISTICS")
    print("="*70)
    
    # Check if language column exists
    cursor.execute("PRAGMA table_info(gm_articles)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'detected_language' not in columns:
        print("⚠️  Language detection not yet run on any articles")
        conn.close()
        return
    
    # Count articles by language
    cursor.execute("""
        SELECT 
            detected_language,
            COUNT(*) as count,
            ROUND(AVG(language_confidence), 4) as avg_confidence,
            ROUND(MIN(language_confidence), 4) as min_confidence,
            ROUND(MAX(language_confidence), 4) as max_confidence
        FROM gm_articles
        WHERE detected_language IS NOT NULL
        GROUP BY detected_language
        ORDER BY count DESC
        LIMIT 20
    """)
    
    results = cursor.fetchall()
    
    if not results:
        print("⚠️  No articles with detected languages yet")
    else:
        print(f"\n{'Language':<10} {'Count':<10} {'Avg Conf':<12} {'Min Conf':<12} {'Max Conf':<12}")
        print("-"*70)
        for lang, count, avg_conf, min_conf, max_conf in results:
            print(f"{lang:<10} {count:<10,} {avg_conf:<12} {min_conf:<12} {max_conf:<12}")
    
    # Count translated articles
    cursor.execute("""
        SELECT COUNT(*) 
        FROM gm_articles 
        WHERE translated_title IS NOT NULL
    """)
    translated_count = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM gm_articles 
        WHERE translated_content IS NOT NULL
    """)
    translated_content_count = cursor.fetchone()[0]
    
    print(f"\n📊 Articles with translated titles: {translated_count:,}")
    print(f"📊 Articles with translated content: {translated_content_count:,}")
    
    conn.close()


def main():
    """Main execution"""
    print("="*70)
    print("LANGUAGE DETECTION & TRANSLATION SCHEMA UPDATE")
    print("="*70)
    print()
    
    if add_language_columns():
        show_language_stats()
        return 0
    else:
        return 1


if __name__ == '__main__':
    exit(main())
