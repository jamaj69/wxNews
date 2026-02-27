#!/usr/bin/env python3
"""
Fix sources with empty names by extracting names from RSS feed titles
"""

import asyncio
import aiohttp
import feedparser
import logging
from sqlalchemy import create_engine, MetaData, Table, select, update
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_rss_feed_name(session, url):
    """Extract feed title from RSS feed"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                return None
            
            content = await response.text()
            feed = feedparser.parse(content)
            
            # Try to get feed title
            if hasattr(feed, 'feed') and hasattr(feed.feed, 'title'):
                return feed.feed.title.strip()
            
            return None
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
        return None


def generate_fallback_name(url, source_id):
    """Generate a fallback name from URL or source_id"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        
        if domain:
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            
            # Remove TLD and capitalize
            parts = domain.split('.')
            if len(parts) >= 2:
                name = parts[-2].upper()
                return name
        
        # Fallback: use source_id
        return source_id.replace('rss-', '').replace('-', ' ').title()
    except:
        return source_id.replace('rss-', '').replace('-', ' ').title()


async def fix_empty_names(db_path='predator_news.db'):
    """Fix all sources with empty or null names"""
    
    # Database connection
    eng = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False}
    )
    
    meta = MetaData()
    gm_sources = Table('gm_sources', meta, autoload_with=eng)
    
    # Get sources with empty names
    with eng.connect() as conn:
        stmt = select(gm_sources).where(
            (gm_sources.c.name == None) | 
            (gm_sources.c.name == '') |
            (gm_sources.c.name == ' ')
        )
        empty_sources = conn.execute(stmt).fetchall()
    
    logger.info(f"Found {len(empty_sources)} sources with empty names")
    
    if not empty_sources:
        logger.info("No sources to fix!")
        return
    
    # Process sources
    updated = 0
    failed = 0
    
    async with aiohttp.ClientSession() as session:
        for source in empty_sources:
            source_id = source[0]
            url = source[3]  # URL is column 3
            
            logger.info(f"Processing {source_id}...")
            
            # Try to get name from RSS feed
            name = await get_rss_feed_name(session, url)
            
            # If failed, generate from URL/ID
            if not name or name.strip() == '':
                name = generate_fallback_name(url, source_id)
                logger.info(f"  Using fallback name: {name}")
            else:
                logger.info(f"  Found RSS feed name: {name}")
            
            # Update database
            try:
                with eng.connect() as conn:
                    stmt = update(gm_sources).where(
                        gm_sources.c.id_source == source_id
                    ).values(
                        name=name,
                        description=f"{name} - RSS Feed"
                    )
                    conn.execute(stmt)
                    conn.commit()
                    updated += 1
                    logger.info(f"  ✅ Updated: {source_id} -> {name}")
            except Exception as e:
                logger.error(f"  ❌ Failed to update {source_id}: {e}")
                failed += 1
    
    logger.info("\n" + "=" * 80)
    logger.info("📊 FIX SUMMARY")
    logger.info(f"  Total sources with empty names: {len(empty_sources)}")
    logger.info(f"  Successfully updated: {updated}")
    logger.info(f"  Failed: {failed}")
    logger.info("=" * 80)


if __name__ == '__main__':
    asyncio.run(fix_empty_names())
