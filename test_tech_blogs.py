#!/usr/bin/env python3
"""
Test RSS collection from newly added tech blogs
"""

import asyncio
import aiohttp
import feedparser
import logging
from sqlalchemy import create_engine, MetaData, Table, select
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_feed(session, source_name, url, language):
    """Test a single RSS feed"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status != 200:
                logger.warning(f"❌ {source_name} ({language}): HTTP {response.status}")
                return None
            
            content = await response.text()
            feed = feedparser.parse(content)
            
            if not feed.entries:
                logger.warning(f"⚠️  {source_name} ({language}): 0 entries")
                return None
            
            logger.info(f"✅ {source_name} ({language}): {len(feed.entries)} entries")
            return {
                'source': source_name,
                'language': language,
                'count': len(feed.entries),
                'first_title': feed.entries[0].get('title', 'N/A') if feed.entries else 'N/A'
            }
            
    except asyncio.TimeoutError:
        logger.error(f"⏱️  {source_name} ({language}): Timeout")
        return None
    except Exception as e:
        logger.error(f"❌ {source_name} ({language}): {str(e)}")
        return None


async def test_tech_blogs():
    """Test newly added tech blogs"""
    
    # Database connection
    db_path = 'predator_news.db'
    eng = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False}
    )
    
    meta = MetaData()
    sources_table = Table('gm_sources', meta, autoload_with=eng)
    
    # Get newly added tech sources (exclude ones we already had)
    with eng.connect() as conn:
        # Get sources with specific new names
        new_sources_names = [
            'Xataka', 'Genbeta', 'Hipertextual',  # ES
            'Tecnoblog', 'Pplware', 'MacMagazine',  # PT
            'HDblog', 'TuttoAndroid', 'iSpazio',  # IT
            'Gizmodo', '9to5Mac', 'How-To Geek'  # EN
        ]
        
        stmt = select(sources_table.c.name, sources_table.c.url, sources_table.c.language).where(
            sources_table.c.category == 'technology'
        ).where(
            sources_table.c.id_source.like('rss-%')
        ).where(
            sources_table.c.name.in_(new_sources_names)
        )
        
        results = conn.execute(stmt).fetchall()
        
        if not results:
            logger.error("No test sources found!")
            return
        
        logger.info(f"\n{'='*80}")
        logger.info(f"🧪 Testing {len(results)} tech blogs from new imports")
        logger.info(f"{'='*80}\n")
        
        # Test feeds
        async with aiohttp.ClientSession() as session:
            tasks = [test_feed(session, name, url, lang) for name, url, lang in results]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter successful results
            successful = [r for r in results if r and isinstance(r, dict)]
            failed = len(results) - len(successful)
            
            logger.info(f"\n{'='*80}")
            logger.info(f"📊 TEST SUMMARY")
            logger.info(f"  Total tested: {len(results)}")
            logger.info(f"  ✅ Successful: {len(successful)}")
            logger.info(f"  ❌ Failed: {failed}")
            
            if successful:
                logger.info(f"\n📰 Sample articles:")
                for result in successful[:5]:  # Show first 5
                    logger.info(f"  • {result['source']}: \"{result['first_title']}\"")
            
            # By language stats
            by_lang = {}
            for result in successful:
                lang = result['language']
                by_lang[lang] = by_lang.get(lang, 0) + 1
            
            if by_lang:
                logger.info(f"\n🌍 By language:")
                for lang, count in sorted(by_lang.items()):
                    logger.info(f"  {lang}: {count} working feeds")
            
            logger.info(f"{'='*80}")


if __name__ == '__main__':
    asyncio.run(test_tech_blogs())
