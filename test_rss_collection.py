#!/usr/bin/env python3
"""
Test RSS Feed Collection
Collects news from RSS feeds in database and stores articles
"""

import asyncio
import aiohttp
import feedparser
import logging
from datetime import datetime
from sqlalchemy import create_engine, MetaData, Table, select
from sqlalchemy.dialects.sqlite import insert
from decouple import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RSSCollector:
    def __init__(self, db_path='predator_news.db'):
        self.db_path = db_path
        self.db_lock = asyncio.Lock()
        
        # Load RSS configuration from .env
        self.timeout = int(config('RSS_TIMEOUT', default=15))
        self.max_concurrent = int(config('RSS_MAX_CONCURRENT', default=10))
        self.batch_size = int(config('RSS_BATCH_SIZE', default=20))
        
        logger.info(f"RSS Configuration: timeout={self.timeout}s, max_concurrent={self.max_concurrent}, batch_size={self.batch_size}")
        
        # Database connection
        self.eng = create_engine(
            f'sqlite:///{db_path}',
            connect_args={'timeout': 30, 'check_same_thread': False},
            pool_pre_ping=True
        )
        
        # Tables
        meta = MetaData()
        self.sources_table = Table('gm_sources', meta, autoload_with=self.eng)
        self.articles_table = Table('gm_articles', meta, autoload_with=self.eng)
        
        logger.info(f"Initialized RSSCollector with database: {db_path}")
    
    async def fetch_rss(self, session, url):
        """Fetch and parse RSS feed with configured timeout"""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.timeout)) as response:
                if response.status == 200:
                    content = await response.text()
                    parsed = feedparser.parse(content)
                    
                    if hasattr(parsed, 'bozo_exception'):
                        logger.warning(f"⚠️  Invalid XML: {url[:60]}... - {parsed.bozo_exception}")
                        return None
                    
                    return parsed
                else:
                    logger.warning(f"⚠️  HTTP {response.status}: {url[:60]}...")
                    return None
                    
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  Timeout ({self.timeout}s): {url[:60]}...")
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching {url[:60]}...: {e}", exc_info=False)
            return None
    
    async def process_feed(self, session, source_id, source_name, feed_url):
        """Process a single RSS feed"""
        logger.debug(f"Processing: {source_name} ({feed_url[:60]}...)")
        
        # Fetch RSS feed
        parsed = await self.fetch_rss(session, feed_url)
        if not parsed or not parsed.entries:
            return 0, 0
        
        logger.info(f"📥 [{source_name}] Received {len(parsed.entries)} entries")
        
        articles_inserted = 0
        articles_skipped = 0
        
        # Process each entry
        for entry in parsed.entries:
            # Extract article data
            article_url = entry.get('link', '')
            if not article_url:
                continue
            
            title = entry.get('title', 'No title')
            description = entry.get('summary', entry.get('description', ''))
            
            # Try to get publication date
            pub_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d %H:%M:%S')
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                pub_date = datetime(*entry.updated_parsed[:6]).strftime('%Y-%m-%d %H:%M:%S')
            else:
                pub_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Get author
            author = entry.get('author', '')
            
            # Generate article ID (using URL hash for simplicity)
            article_id = f"rss-{abs(hash(article_url)) % 10**12}"
            
            # Insert into database
            article_data = {
                'id_article': article_id,
                'id_source': source_id,
                'title': title[:500] if title else '',
                'description': description[:2000] if description else '',
                'url': article_url[:500] if article_url else '',
                'author': author[:200] if author else '',
                'publishedAt': pub_date,
                'urlToImage': ''
            }
            
            async with self.db_lock:
                with self.eng.connect() as conn:
                    try:
                        ins = insert(self.articles_table).values(**article_data)
                        ins_ignore = ins.on_conflict_do_nothing()
                        result = conn.execute(ins_ignore)
                        conn.commit()
                        
                        if result.rowcount > 0:
                            articles_inserted += 1
                            logger.info(f"  ✅ [{source_name}] {title[:60]}...")
                        else:
                            articles_skipped += 1
                            logger.debug(f"  ⏭️  [{source_name}] Already exists: {title[:40]}...")
                            
                    except Exception as e:
                        logger.error(f"  ❌ Failed to insert '{title[:40]}...': {e}")
                        conn.rollback()
        
        return articles_inserted, articles_skipped
    
    async def process_feed_with_semaphore(self, session, semaphore, source_id, source_name, feed_url):
        """Process a single RSS feed with semaphore control"""
        async with semaphore:
            return await self.process_feed(session, source_id, source_name, feed_url)
    
    async def collect_all_rss(self, limit=10):
        """Collect news from all RSS feeds in database with parallel processing"""
        logger.info("=" * 80)
        logger.info("Starting RSS collection")
        logger.info("=" * 80)
        
        # Get RSS feeds from database
        with self.eng.connect() as conn:
            stmt = select(self.sources_table).where(
                self.sources_table.c.id_source.like('rss-%')
            ).limit(limit)
            result = conn.execute(stmt)
            feeds = result.fetchall()
        
        logger.info(f"Found {len(feeds)} RSS feeds in database (testing first {limit})")
        
        if not feeds:
            logger.warning("No RSS feeds found in database")
            return
        
        # Process feeds with controlled concurrency
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; NewsGatherer/1.0)'
        }
        
        total_inserted = 0
        total_skipped = 0
        successful_feeds = 0
        failed_feeds = 0
        
        # Semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async with aiohttp.ClientSession(headers=headers) as session:
            # Process feeds in batches
            for i in range(0, len(feeds), self.batch_size):
                batch = feeds[i:i+self.batch_size]
                batch_num = i // self.batch_size + 1
                total_batches = (len(feeds) - 1) // self.batch_size + 1
                
                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} feeds)...")
                
                # Create tasks for this batch
                tasks = []
                for feed in batch:
                    source_id = feed.id_source
                    source_name = feed.name or source_id
                    feed_url = feed.url
                    
                    if not feed_url:
                        logger.warning(f"⚠️  No URL for source: {source_id}")
                        continue
                    
                    task = self.process_feed_with_semaphore(
                        session, semaphore, source_id, source_name, feed_url
                    )
                    tasks.append(task)
                
                # Execute batch in parallel with semaphore control
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results
                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"❌ Task failed: {result}")
                        failed_feeds += 1
                    elif result:
                        inserted, skipped = result
                        if inserted > 0 or skipped > 0:
                            successful_feeds += 1
                        total_inserted += inserted
                        total_skipped += skipped
                
                # Summary for this batch
                logger.info(f"Batch {batch_num} complete: {total_inserted} inserted, {total_skipped} skipped so far")
        
        # Final summary
        logger.info("=" * 80)
        logger.info(f"📊 COLLECTION SUMMARY")
        logger.info(f"  Feeds processed: {len(feeds)}")
        logger.info(f"  Successful feeds: {successful_feeds}")
        logger.info(f"  Failed feeds: {failed_feeds}")
        logger.info(f"  Articles inserted: {total_inserted}")
        logger.info(f"  Articles skipped: {total_skipped}")
        logger.info("=" * 80)


async def main():
    collector = RSSCollector()
    
    # Test with first 10 RSS feeds (use limit=None for all)
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    await collector.collect_all_rss(limit=limit)


if __name__ == '__main__':
    asyncio.run(main())
