#!/usr/bin/env python3
"""
Backfill missing article content by fetching from URLs.

This script:
1. Finds all articles with empty/missing content
2. Attempts to fetch content from their URLs
3. Updates database with enriched data
4. Preserves original RSS data on failure
5. Provides detailed progress reporting

Usage:
    python3 backfill_article_content.py [options]
    
Options:
    --limit N       Process only N articles (default: all)
    --dry-run       Show what would be done without updating database
    --source ID     Process only articles from specific source
    --timeout N     Timeout for each fetch in seconds (default: 10)
    --batch N       Process in batches of N articles (default: 100)
    --delay N       Delay between fetches in seconds (default: 1)
"""

import sys
import argparse
import time
from datetime import datetime
from pathlib import Path
import logging

from sqlalchemy import create_engine, Table, Column, String, Text, MetaData
from sqlalchemy import select, update
from decouple import config

from article_fetcher import fetch_article_content


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backfill.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection."""
    db_path = config('DB_PATH', default='predator_news.db')
    if not Path(db_path).is_absolute():
        script_dir = Path(__file__).parent
        db_path = script_dir / db_path
    
    engine = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False}
    )
    return engine


def get_articles_needing_enrichment(engine, source_id=None, limit=None):
    """
    Get articles that need content enrichment.
    
    Returns list of tuples: (id_article, id_source, url, author, description, content)
    """
    meta = MetaData()
    gm_articles = Table('gm_articles', meta, autoload_with=engine)
    gm_sources = Table('gm_sources', meta, autoload_with=engine)
    
    with engine.connect() as conn:
        # Build query for articles with missing content
        query = select(
            gm_articles.c.id_article,
            gm_articles.c.id_source,
            gm_articles.c.url,
            gm_articles.c.author,
            gm_articles.c.description,
            gm_articles.c.content,
            gm_articles.c.title,
            gm_sources.c.name.label('source_name')
        ).select_from(
            gm_articles.join(gm_sources, gm_articles.c.id_source == gm_sources.c.id_source)
        ).where(
            # At least one field is empty
            (gm_articles.c.author == '') |
            (gm_articles.c.author == None) |
            (gm_articles.c.description == '') |
            (gm_articles.c.description == None) |
            (gm_articles.c.content == '') |
            (gm_articles.c.content == None)
        ).where(
            # URL is not empty (need URL to fetch)
            (gm_articles.c.url != '') &
            (gm_articles.c.url != None)
        )
        
        # Filter by source if specified
        if source_id:
            query = query.where(gm_articles.c.id_source == source_id)
        
        # Apply limit
        if limit:
            query = query.limit(limit)
        
        result = conn.execute(query)
        articles = result.fetchall()
        
    return articles


def enrich_article(article, timeout=10):
    """
    Attempt to enrich a single article.
    
    Returns: dict with updates, or None if no enrichment possible
    """
    id_article, id_source, url, author, description, content, title, source_name = article
    
    # Track what's missing
    missing = []
    if not author or not author.strip():
        missing.append('author')
    if not description or not description.strip():
        missing.append('description')
    if not content or not content.strip():
        missing.append('content')
    
    if not missing:
        return None
    
    logger.debug(f"Fetching {', '.join(missing)} for: {title[:50]}...")
    
    try:
        # Fetch content from URL
        result = fetch_article_content(url, timeout=timeout)
        
        if not result or not result.get('success'):
            logger.debug(f"  ❌ Fetch failed for: {url}")
            return None
        
        # Prepare updates
        updates = {}
        enriched = []
        
        if 'author' in missing and result.get('author'):
            updates['author'] = result['author'][:200]
            enriched.append('author')
        
        if 'description' in missing and result.get('description'):
            updates['description'] = result['description'][:1000]
            enriched.append('description')
        
        if 'content' in missing and result.get('content'):
            updates['content'] = result['content'][:2000]
            enriched.append('content')
        
        if enriched:
            logger.info(f"  ✅ [{source_name}] {title[:40]}... → {', '.join(enriched)}")
            return updates
        else:
            logger.debug(f"  ⚠️  Fetch succeeded but no useful data for: {title[:40]}...")
            return None
            
    except Exception as e:
        logger.warning(f"  ⚠️  Error fetching {url}: {e}")
        return None


def update_article_in_db(engine, article_id, updates):
    """Update article in database."""
    meta = MetaData()
    gm_articles = Table('gm_articles', meta, autoload_with=engine)
    
    with engine.connect() as conn:
        stmt = update(gm_articles).where(
            gm_articles.c.id_article == article_id
        ).values(**updates)
        conn.execute(stmt)
        conn.commit()


def main():
    parser = argparse.ArgumentParser(
        description='Backfill missing article content from URLs'
    )
    parser.add_argument('--limit', type=int, help='Process only N articles')
    parser.add_argument('--dry-run', action='store_true', help='Don\'t update database')
    parser.add_argument('--source', type=str, help='Process only specific source ID')
    parser.add_argument('--timeout', type=int, default=10, help='Fetch timeout (seconds)')
    parser.add_argument('--batch', type=int, default=100, help='Batch size')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay between fetches (seconds)')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("Article Content Backfill")
    logger.info("=" * 80)
    
    # Get database connection
    engine = get_db_connection()
    logger.info(f"Connected to database: {engine.url}")
    
    # Get articles needing enrichment
    logger.info("Querying articles with missing content...")
    articles = get_articles_needing_enrichment(engine, args.source, args.limit)
    logger.info(f"Found {len(articles)} articles needing enrichment")
    
    if not articles:
        logger.info("No articles to process. Exiting.")
        return 0
    
    # Show sample
    logger.info("\nSample articles to process:")
    for i, article in enumerate(articles[:5]):
        id_article, id_source, url, author, description, content, title, source_name = article
        missing = []
        if not author or not author.strip():
            missing.append('author')
        if not description or not description.strip():
            missing.append('desc')
        if not content or not content.strip():
            missing.append('content')
        logger.info(f"  [{source_name}] {title[:50]}... (missing: {', '.join(missing)})")
    
    if args.dry_run:
        logger.info("\n⚠️  DRY RUN MODE - No database updates will be made")
    
    # Confirm
    if not args.dry_run and not args.yes:
        response = input(f"\nProcess {len(articles)} articles? [y/N]: ")
        if response.lower() != 'y':
            logger.info("Cancelled by user.")
            return 0
    
    # Process articles
    logger.info("\nStarting enrichment process...")
    logger.info(f"Batch size: {args.batch}, Delay: {args.delay}s, Timeout: {args.timeout}s")
    logger.info("-" * 80)
    
    stats = {
        'total': len(articles),
        'processed': 0,
        'enriched': 0,
        'failed': 0,
        'skipped': 0,
        'by_field': {'author': 0, 'description': 0, 'content': 0}
    }
    
    start_time = time.time()
    
    for i, article in enumerate(articles, 1):
        id_article = article[0]
        title = article[6]
        
        try:
            # Enrich article
            updates = enrich_article(article, timeout=args.timeout)
            
            stats['processed'] += 1
            
            if updates:
                # Track which fields were enriched
                for field in updates.keys():
                    if field in stats['by_field']:
                        stats['by_field'][field] += 1
                
                # Update database
                if not args.dry_run:
                    update_article_in_db(engine, id_article, updates)
                
                stats['enriched'] += 1
            else:
                stats['failed'] += 1
            
            # Progress report every batch
            if i % args.batch == 0:
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                eta = (stats['total'] - i) / rate if rate > 0 else 0
                
                logger.info(f"\nProgress: {i}/{stats['total']} ({i*100//stats['total']}%)")
                logger.info(f"  Enriched: {stats['enriched']}, Failed: {stats['failed']}")
                logger.info(f"  Rate: {rate:.1f} articles/sec, ETA: {eta/60:.1f} min")
                logger.info(f"  Fields: author={stats['by_field']['author']}, "
                          f"desc={stats['by_field']['description']}, "
                          f"content={stats['by_field']['content']}")
            
            # Delay between requests
            if args.delay > 0:
                time.sleep(args.delay)
                
        except KeyboardInterrupt:
            logger.info("\n\n⚠️  Interrupted by user")
            break
        except Exception as e:
            logger.error(f"  ❌ Unexpected error processing {title[:40]}...: {e}")
            stats['failed'] += 1
    
    # Final report
    elapsed = time.time() - start_time
    logger.info("\n" + "=" * 80)
    logger.info("FINAL REPORT")
    logger.info("=" * 80)
    logger.info(f"Total articles: {stats['total']}")
    logger.info(f"Processed: {stats['processed']}")
    logger.info(f"Successfully enriched: {stats['enriched']} ({stats['enriched']*100//stats['processed'] if stats['processed'] > 0 else 0}%)")
    logger.info(f"Failed/No data: {stats['failed']}")
    logger.info(f"\nFields enriched:")
    logger.info(f"  Author: {stats['by_field']['author']}")
    logger.info(f"  Description: {stats['by_field']['description']}")
    logger.info(f"  Content: {stats['by_field']['content']}")
    logger.info(f"\nTime elapsed: {elapsed/60:.1f} minutes")
    logger.info(f"Average rate: {stats['processed']/elapsed:.1f} articles/second")
    
    if args.dry_run:
        logger.info("\n⚠️  DRY RUN - No changes were made to the database")
    else:
        logger.info(f"\n✅ Updated {stats['enriched']} articles in database")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
