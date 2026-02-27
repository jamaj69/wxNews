#!/usr/bin/env python3
"""
Complete News Collection Test
Tests NewsAPI, MediaStack, and RSS collection with URL capture and RSS discovery
"""

import asyncio
import logging
import sqlite3
from datetime import datetime
from wxAsyncNewsGather import NewsGather

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_complete_collection():
    """Test complete news collection from all sources"""
    print("="*80)
    print("🧪 COMPLETE NEWS COLLECTION TEST")
    print("="*80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Get initial statistics
    conn = sqlite3.connect('predator_news.db')
    cursor = conn.cursor()
    
    print("📊 Initial Database Statistics:")
    print("-" * 80)
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources")
    initial_sources = cursor.fetchone()[0]
    print(f"Total sources: {initial_sources}")
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source LIKE 'rss-%'")
    rss_sources = cursor.fetchone()[0]
    print(f"  - RSS sources: {rss_sources}")
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source LIKE 'mediastack-%'")
    mediastack_sources = cursor.fetchone()[0]
    print(f"  - MediaStack sources: {mediastack_sources}")
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source NOT LIKE 'rss-%' AND id_source NOT LIKE 'mediastack-%'")
    newsapi_sources = cursor.fetchone()[0]
    print(f"  - NewsAPI sources: {newsapi_sources}")
    
    cursor.execute("SELECT COUNT(*) FROM gm_articles")
    initial_articles = cursor.fetchone()[0]
    print(f"Total articles: {initial_articles}")
    
    print()
    
    # Create event loop and NewsGather
    loop = asyncio.get_event_loop()
    
    print("📋 Initializing NewsGather...")
    news_gather = NewsGather(loop)
    
    print("\n🔄 Starting Collection Cycle...")
    print("-" * 80)
    
    # Run one complete collection cycle
    print("\n1️⃣  NewsAPI Collection (EN, PT, ES, IT)...")
    await news_gather.async_getALLNews()
    
    print("\n2️⃣  RSS Collection (322 sources)...")
    await news_gather.collect_rss_feeds()
    
    print("\n3️⃣  MediaStack Collection (PT, ES, IT)...")
    await news_gather.collect_mediastack()
    
    # Wait a bit for RSS discovery tasks to complete
    print("\n⏳ Waiting for RSS discovery tasks to complete...")
    await asyncio.sleep(5)
    
    print("\n" + "="*80)
    print("📊 Final Database Statistics:")
    print("-" * 80)
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources")
    final_sources = cursor.fetchone()[0]
    print(f"Total sources: {final_sources} (+{final_sources - initial_sources})")
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source LIKE 'rss-%'")
    rss_sources_final = cursor.fetchone()[0]
    print(f"  - RSS sources: {rss_sources_final} (+{rss_sources_final - rss_sources})")
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source LIKE 'mediastack-%'")
    mediastack_sources_final = cursor.fetchone()[0]
    print(f"  - MediaStack sources: {mediastack_sources_final} (+{mediastack_sources_final - mediastack_sources})")
    
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source NOT LIKE 'rss-%' AND id_source NOT LIKE 'mediastack-%'")
    newsapi_sources_final = cursor.fetchone()[0]
    print(f"  - NewsAPI sources: {newsapi_sources_final} (+{newsapi_sources_final - newsapi_sources})")
    
    cursor.execute("SELECT COUNT(*) FROM gm_articles")
    final_articles = cursor.fetchone()[0]
    print(f"Total articles: {final_articles} (+{final_articles - initial_articles})")
    
    print("\n" + "="*80)
    print("🔗 Sample Source URLs Captured (last 10 non-RSS sources):")
    print("-" * 80)
    
    cursor.execute("""
        SELECT id_source, name, url, category, language
        FROM gm_sources 
        WHERE id_source NOT LIKE 'rss-%' 
        AND url != ''
        ORDER BY rowid DESC 
        LIMIT 10
    """)
    
    for row in cursor.fetchall():
        source_id, name, url, category, language = row
        source_type = "MediaStack" if source_id.startswith('mediastack-') else "NewsAPI"
        print(f"[{source_type:10}] {name[:30]:30} | {language:2} | {url}")
    
    print("\n" + "="*80)
    print("📡 RSS Feeds Discovered (sample of 10):")
    print("-" * 80)
    
    cursor.execute("""
        SELECT id_source, name, url, language
        FROM gm_sources 
        WHERE id_source LIKE 'rss-%' 
        ORDER BY rowid DESC 
        LIMIT 10
    """)
    
    rss_count = 0
    for row in cursor.fetchall():
        source_id, name, url, language = row
        print(f"{name[:40]:40} | {language:2} | {url[:60]}")
        rss_count += 1
    
    if rss_count == 0:
        print("(No new RSS feeds discovered in this run)")
    
    print("\n" + "="*80)
    print("📈 Collection Summary:")
    print("-" * 80)
    print(f"✅ New sources added: {final_sources - initial_sources}")
    print(f"✅ New articles collected: {final_articles - initial_articles}")
    print(f"✅ RSS feeds discovered: {rss_sources_final - rss_sources}")
    
    print("\n" + "="*80)
    print("🎯 Sources with URLs Available for RSS Discovery:")
    print("-" * 80)
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM gm_sources 
        WHERE id_source NOT LIKE 'rss-%' 
        AND url != '' 
        AND url IS NOT NULL
    """)
    sources_with_urls = cursor.fetchone()[0]
    print(f"Total sources with URLs: {sources_with_urls}")
    
    cursor.execute("""
        SELECT language, COUNT(*) 
        FROM gm_sources 
        WHERE id_source NOT LIKE 'rss-%' 
        AND url != '' 
        AND url IS NOT NULL
        GROUP BY language
        ORDER BY COUNT(*) DESC
    """)
    
    print("\nBy language:")
    for row in cursor.fetchall():
        lang, count = row
        print(f"  {lang or 'unknown':2} : {count} sources")
    
    conn.close()
    
    print("\n" + "="*80)
    print(f"✅ Test Complete at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

if __name__ == '__main__':
    asyncio.run(test_complete_collection())
