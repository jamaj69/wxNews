#!/usr/bin/env python3
"""
Test RSS collection by language
Tests a few sources from each language to verify they work
"""

import asyncio
import sys
from sqlalchemy import create_engine, MetaData, Table, select

# Import the collector
sys.path.insert(0, '.')
from test_rss_collection import RSSCollector


async def test_by_language(language, limit=5):
    """Test RSS collection for a specific language"""
    print(f"\n{'='*80}")
    print(f"Testing {limit} RSS sources for language: {language.upper()}")
    print('='*80)
    
    collector = RSSCollector()
    
    # Get RSS feeds for this language
    with collector.eng.connect() as conn:
        stmt = select(collector.sources_table).where(
            collector.sources_table.c.id_source.like('rss-%'),
            collector.sources_table.c.language == language
        ).limit(limit)
        result = conn.execute(stmt)
        feeds = result.fetchall()
    
    if not feeds:
        print(f"⚠️  No RSS feeds found for language: {language}")
        return
    
    print(f"Found {len(feeds)} feeds for {language}")
    
    # Process feeds
    import aiohttp
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; NewsGatherer/1.0)'
    }
    
    successful = 0
    failed = 0
    total_articles = 0
    
    semaphore = asyncio.Semaphore(collector.max_concurrent)
    
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = []
        for feed in feeds:
            source_id = feed.id_source
            source_name = feed.name or source_id
            feed_url = feed.url
            
            if not feed_url:
                print(f"⚠️  No URL for source: {source_id}")
                continue
            
            task = collector.process_feed_with_semaphore(
                session, semaphore, source_id, source_name, feed_url
            )
            tasks.append((source_name, task))
        
        # Execute tasks
        for source_name, task in tasks:
            try:
                result = await task
                if result:
                    inserted, skipped = result
                    if inserted > 0 or skipped > 0:
                        successful += 1
                        total_articles += inserted
                        print(f"  ✅ {source_name}: {inserted} new, {skipped} existing")
                    else:
                        failed += 1
                        print(f"  ❌ {source_name}: No articles")
            except Exception as e:
                failed += 1
                print(f"  ❌ {source_name}: {e}")
    
    print(f"\n📊 Summary for {language.upper()}:")
    print(f"  Successful: {successful}/{len(feeds)}")
    print(f"  Failed: {failed}/{len(feeds)}")
    print(f"  New articles collected: {total_articles}")


async def main():
    """Test RSS collection for all languages"""
    
    # Test each language
    languages = ['en', 'es', 'pt', 'it']
    sources_per_lang = 5
    
    if len(sys.argv) > 1:
        # Test specific language
        lang = sys.argv[1].lower()
        if lang in languages:
            await test_by_language(lang, limit=10)
        else:
            print(f"Invalid language: {lang}")
            print(f"Available: {', '.join(languages)}")
            return
    else:
        # Test all languages
        for lang in languages:
            await test_by_language(lang, limit=sources_per_lang)
            await asyncio.sleep(1)  # Small delay between languages
    
    print("\n" + "="*80)
    print("✅ Testing complete!")
    print("="*80)


if __name__ == '__main__':
    asyncio.run(main())
