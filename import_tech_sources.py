#!/usr/bin/env python3
"""
Import technology sources from NewsAPI, checking for RSS endpoints first.
Prefers RSS over NewsAPI direct access.
"""

import asyncio
import aiohttp
import json
import logging
from urllib.parse import urlparse
from sqlalchemy import create_engine, MetaData, Table, select
from sqlalchemy.dialects.sqlite import insert
import feedparser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def discover_rss_feed(session, domain, source_name):
    """
    Try to discover RSS feed for a domain.
    Checks common RSS locations.
    """
    common_rss_paths = [
        '/feed',
        '/rss',
        '/feed/',
        '/rss/',
        '/feeds/posts/default',
        '/rss.xml',
        '/feed.xml',
        '/atom.xml',
        '/index.xml',
        '/?feed=rss2',
        '/blog/feed',
    ]
    
    # Clean domain
    if domain.startswith('www.'):
        domain = domain[4:]
    
    base_urls = [
        f'https://{domain}',
        f'https://www.{domain}'
    ]
    
    for base_url in base_urls:
        for path in common_rss_paths:
            rss_url = base_url + path
            try:
                async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        content = await response.text()
                        # Check if it's actually an RSS feed
                        if any(tag in content[:1000] for tag in ['<rss', '<feed', '<channel']):
                            # Validate with feedparser
                            feed = feedparser.parse(content)
                            if feed.entries or (hasattr(feed, 'feed') and hasattr(feed.feed, 'title')):
                                logger.info(f"  ✅ Found RSS: {rss_url}")
                                return rss_url
            except:
                continue
    
    return None


async def get_rss_feed_name(session, rss_url):
    """Extract feed title from RSS feed"""
    try:
        async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                return None
            
            content = await response.text()
            feed = feedparser.parse(content)
            
            if hasattr(feed, 'feed') and hasattr(feed.feed, 'title'):
                return feed.feed.title.strip()
            
            return None
    except:
        return None


async def process_tech_sources(api_key, db_path='predator_news.db'):
    """
    Fetch technology sources from NewsAPI and import them.
    Checks for RSS feeds first, falls back to NewsAPI.
    """
    
    # Fetch tech sources from NewsAPI
    url = f"https://newsapi.org/v2/sources?apiKey={api_key}&category=technology"
    
    logger.info("Fetching technology sources from NewsAPI...")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch sources: HTTP {response.status}")
                return
            
            data = await response.json()
            
            if data.get('status') != 'ok':
                logger.error(f"API Error: {data}")
                return
            
            sources = data.get('sources', [])
            logger.info(f"Found {len(sources)} technology sources")
            
            # Database connection
            eng = create_engine(
                f'sqlite:///{db_path}',
                connect_args={'timeout': 30, 'check_same_thread': False}
            )
            
            meta = MetaData()
            gm_sources = Table('gm_sources', meta, autoload_with=eng)
            
            stats = {
                'total': len(sources),
                'rss_found': 0,
                'rss_added': 0,
                'newsapi_added': 0,
                'already_exist': 0,
                'errors': 0
            }
            
            for source in sources:
                source_id = source['id']
                source_name = source['name']
                source_url = source['url']
                description = source['description']
                language = source['language']
                country = source['country']
                
                logger.info(f"\n{'='*80}")
                logger.info(f"Processing: {source_name}")
                logger.info(f"  URL: {source_url}")
                
                # Check if already exists in database (NewsAPI or RSS)
                with eng.connect() as conn:
                    # Check NewsAPI source
                    stmt = select(gm_sources).where(gm_sources.c.id_source == source_id)
                    existing_newsapi = conn.execute(stmt).fetchone()
                    
                    # Check RSS source
                    rss_id = f"rss-{source_id}"
                    stmt = select(gm_sources).where(gm_sources.c.id_source == rss_id)
                    existing_rss = conn.execute(stmt).fetchone()
                
                if existing_newsapi or existing_rss:
                    logger.info(f"  ⏭️  Already exists (NewsAPI: {bool(existing_newsapi)}, RSS: {bool(existing_rss)})")
                    stats['already_exist'] += 1
                    continue
                
                # Try to discover RSS feed
                parsed = urlparse(source_url)
                domain = parsed.netloc
                
                rss_url = await discover_rss_feed(session, domain, source_name)
                
                if rss_url:
                    stats['rss_found'] += 1
                    
                    # Get RSS feed name if available
                    rss_name = await get_rss_feed_name(session, rss_url)
                    if rss_name:
                        logger.info(f"  RSS name: {rss_name}")
                    
                    # Add as RSS source
                    try:
                        with eng.connect() as conn:
                            ins = insert(gm_sources).values(
                                id_source=rss_id,
                                name=rss_name if rss_name else source_name,
                                description=description,
                                url=rss_url,
                                category='technology',
                                language=language,
                                country=country
                            )
                            ins = ins.on_conflict_do_nothing()
                            result = conn.execute(ins)
                            conn.commit()
                            
                            if result.rowcount > 0:
                                stats['rss_added'] += 1
                                logger.info(f"  ✅ Added as RSS source: {rss_id}")
                            else:
                                stats['already_exist'] += 1
                    except Exception as e:
                        logger.error(f"  ❌ Failed to add RSS source: {e}")
                        stats['errors'] += 1
                else:
                    logger.info(f"  ⚠️  No RSS feed found, adding as NewsAPI source")
                    
                    # Add as NewsAPI source
                    try:
                        with eng.connect() as conn:
                            ins = insert(gm_sources).values(
                                id_source=source_id,
                                name=source_name,
                                description=description,
                                url=source_url,
                                category='technology',
                                language=language,
                                country=country
                            )
                            ins = ins.on_conflict_do_nothing()
                            result = conn.execute(ins)
                            conn.commit()
                            
                            if result.rowcount > 0:
                                stats['newsapi_added'] += 1
                                logger.info(f"  ✅ Added as NewsAPI source: {source_id}")
                            else:
                                stats['already_exist'] += 1
                    except Exception as e:
                        logger.error(f"  ❌ Failed to add NewsAPI source: {e}")
                        stats['errors'] += 1
    
    # Summary
    logger.info("\n" + "="*80)
    logger.info("📊 IMPORT SUMMARY")
    logger.info(f"  Total tech sources: {stats['total']}")
    logger.info(f"  RSS feeds found: {stats['rss_found']}")
    logger.info(f"  RSS sources added: {stats['rss_added']}")
    logger.info(f"  NewsAPI sources added: {stats['newsapi_added']}")
    logger.info(f"  Already existed: {stats['already_exist']}")
    logger.info(f"  Errors: {stats['errors']}")
    logger.info("="*80)
    
    # Show what was added
    logger.info("\n📋 Verification:")
    with eng.connect() as conn:
        # Count tech category sources
        from sqlalchemy import func
        stmt = select(func.count()).select_from(gm_sources).where(
            gm_sources.c.category == 'technology'
        )
        tech_count = conn.execute(stmt).scalar()
        
        # Count RSS tech sources
        stmt = select(func.count()).select_from(gm_sources).where(
            (gm_sources.c.category == 'technology') & 
            (gm_sources.c.id_source.like('rss-%'))
        )
        rss_tech_count = conn.execute(stmt).scalar()
        
        logger.info(f"  Total technology sources in DB: {tech_count}")
        logger.info(f"  RSS technology sources: {rss_tech_count}")
        logger.info(f"  NewsAPI technology sources: {tech_count - rss_tech_count}")


if __name__ == '__main__':
    API_KEY = '4327173775a746e9b4f2632af3933a86'
    asyncio.run(process_tech_sources(API_KEY))
