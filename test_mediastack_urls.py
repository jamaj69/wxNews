#!/usr/bin/env python3
"""
Test MediaStack URL Capture
Verifies that source URLs are being captured from article URLs
"""

import asyncio
import logging
import sqlite3
from wxAsyncNewsGather import NewsGather

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_mediastack_urls():
    """Test MediaStack URL capture"""
    print("="*80)
    print("🧪 Testing MediaStack URL Capture")
    print("="*80)
    print()
    
    # Get initial stats
    conn = sqlite3.connect('predator_news.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source LIKE 'mediastack-%' AND url != ''")
    initial_with_urls = cursor.fetchone()[0]
    print(f"MediaStack sources with URLs before test: {initial_with_urls}")
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source LIKE 'mediastack-%'")
    total_mediastack = cursor.fetchone()[0]
    print(f"Total MediaStack sources: {total_mediastack}")
    conn.close()
    
    print("\n🔄 Running MediaStack collection...")
    
    loop = asyncio.get_event_loop()
    news_gather = NewsGather(loop)
    
    # Run MediaStack collection
    await news_gather.collect_mediastack()
    
    # Wait for RSS discovery tasks
    await asyncio.sleep(5)
    
    print("\n" + "="*80)
    print("📊 Results:")
    print("="*80)
    
    conn = sqlite3.connect('predator_news.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source LIKE 'mediastack-%' AND url != ''")
    final_with_urls = cursor.fetchone()[0]
    print(f"\nMediaStack sources with URLs after test: {final_with_urls} (+{final_with_urls - initial_with_urls})")
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source LIKE 'mediastack-%'")
    total_mediastack_final = cursor.fetchone()[0]
    print(f"Total MediaStack sources: {total_mediastack_final} (+{total_mediastack_final - total_mediastack})")
    
    print("\n📡 MediaStack Sources with URLs (last 15):")
    print("-" * 80)
    cursor.execute("""
        SELECT name, language, url 
        FROM gm_sources 
        WHERE id_source LIKE 'mediastack-%' 
        AND url != '' 
        ORDER BY rowid DESC 
        LIMIT 15
    """)
    
    for row in cursor.fetchall():
        name, lang, url = row
        print(f"[{lang:2}] {name[:40]:40} | {url}")
    
    conn.close()
    
    print("\n" + "="*80)
    print("✅ Test Complete!")
    print("="*80)

if __name__ == '__main__':
    asyncio.run(test_mediastack_urls())
