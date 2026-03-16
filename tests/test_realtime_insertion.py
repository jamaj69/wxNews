#!/usr/bin/env python3
"""
Test script to insert new articles and watch them appear in wxNewsReader
"""

import sqlite3
import time
import sys

def insert_test_articles(count=5):
    """Insert test articles to trigger real-time updates"""
    
    db = sqlite3.connect('predator_news.db')
    cursor = db.cursor()
    
    # Get a real source ID
    cursor.execute("SELECT id_source FROM gm_sources LIMIT 1")
    source_id = cursor.fetchone()[0]
    
    print(f"🧪 Inserting {count} test articles...")
    print(f"   These should appear in wxNewsReader within 30 seconds!")
    print(f"   Source: {source_id}")
    print()
    
    inserted = []
    current_ms = int(time.time() * 1000)
    
    for i in range(count):
        article_id = f'test-realtime-{current_ms}-{i}'
        title = f'🆕 TEST: Real-Time Update #{i+1} - {time.strftime("%H:%M:%S")}'
        url = f'https://example.com/test-{current_ms}-{i}'
        published_at_gmt = time.strftime('%Y-%m-%d %H:%M:%S')
        inserted_at_ms = current_ms + (i * 1000)  # Stagger by 1 second each
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO gm_articles (
                    id_article, id_source, title, description, url,
                    published_at_gmt, inserted_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                article_id,
                source_id,
                title,
                f'This is a test article inserted at {time.strftime("%H:%M:%S")}. It should appear dynamically in the news reader!',
                url,
                published_at_gmt,
                inserted_at_ms
            ))
            
            inserted.append({
                'id': article_id,
                'title': title,
                'timestamp': inserted_at_ms
            })
            
            print(f"   ✅ Inserted: {title}")
            
        except Exception as e:
            print(f"   ❌ Error inserting article {i+1}: {e}")
    
    db.commit()
    db.close()
    
    print()
    print(f"✨ Successfully inserted {len(inserted)} articles!")
    print()
    print("📺 Watch your wxNewsReader - articles should appear shortly!")
    print("   Look for the notification toast and new cards at the top.")
    print()
    print("Last inserted timestamp:", inserted[-1]['timestamp'] if inserted else 'N/A')
    
    return inserted

if __name__ == '__main__':
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    
    print("=" * 60)
    print("  Real-Time Polling Test - Article Insertion")
    print("=" * 60)
    print()
    
    insert_test_articles(count)
    
    print()
    print("💡 TIP: Run this script multiple times to see articles")
    print("         appearing dynamically as they're inserted!")
