#!/usr/bin/env python3
"""
Sanitize article URLs in database to fix malformed URLs.

This script:
1. Finds articles with malformed URLs (double slashes, redirect chains)
2. Applies URL sanitization from article_fetcher
3. Updates the database with cleaned URLs
4. Reports statistics

Usage:
    python scripts/sanitize_article_urls.py [--dry-run] [--verbose]
"""

import sys
import os
import re
import argparse
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decouple import config
from sqlalchemy import create_engine, MetaData, Table, select, update, func, delete

# Import sanitization from article_fetcher
from article_fetcher import ArticleContentFetcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_path():
    """Get database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(script_dir, db_path)
    return db_path


def find_malformed_urls(engine, articles_table):
    """Find articles with malformed URLs"""
    logger.info("🔍 Scanning for malformed URLs...")
    
    # Query for URLs with double slashes (excluding protocol://)
    stmt = select(
        articles_table.c.id_article,
        articles_table.c.url,
        articles_table.c.title
    ).where(
        # Double slashes in path
        articles_table.c.url.like('%://%//%')
    ).order_by(articles_table.c.id_article)  # Process oldest first
    
    with engine.connect() as conn:
        results = conn.execute(stmt).fetchall()
    
    logger.info(f"📊 Found {len(results)} articles with double-slash URLs")
    
    return results


def find_and_remove_duplicates(engine, articles_table, malformed_articles, dry_run=False):
    """
    Find duplicate target URLs and remove duplicates.
    Checks against ALL existing URLs in database, not just current batch.
    
    Returns: Set of article IDs that are safe to update.
    """
    from collections import defaultdict
    
    logger.info("🔍 Detecting duplicate target URLs...")
    
    # First, get ALL existing URLs from database
    logger.info("  Loading existing URLs from database...")
    existing_urls = {}  # url -> id_article (for already cleaned URLs)
    with engine.connect() as conn:
        stmt = select(articles_table.c.id_article, articles_table.c.url)
        results = conn.execute(stmt).fetchall()
        for row in results:
            existing_urls[row.url] = row.id_article
    
    logger.info(f"  Loaded {len(existing_urls)} existing URLs")
    
    # Now check which sanitized URLs would conflict
    fetcher = ArticleContentFetcher()
    conflicts = []  # Articles that would create duplicates
    safe_ids = set()
    
    for article in malformed_articles:
        id_article = article.id_article
        original_url = article.url
        sanitized = fetcher.sanitize_url(original_url)
        
        # Check if sanitized URL already exists in database
        if sanitized in existing_urls and existing_urls[sanitized] != id_article:
            # This sanitized URL already exists (from previous run)
            # Mark this article for deletion
            conflicts.append((id_article, original_url, sanitized, existing_urls[sanitized]))
        else:
            # Safe to update
            safe_ids.add(id_article)
            # Add to existing URLs to prevent duplicates within this batch
            existing_urls[sanitized] = id_article
    
    # Report findings
    if conflicts:
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"🔍 DUPLICATE DETECTION")
        logger.info("=" * 60)
        logger.info(f"  Found: {len(conflicts)} articles with URLs that already exist")
        logger.info(f"  Safe to update: {len(safe_ids)} articles")
        logger.info("")
        
        # Show examples
        for i, (dup_id, orig_url, target_url, existing_id) in enumerate(conflicts[:3]):
            logger.info(f"  Example #{i+1}:")
            logger.info(f"    Duplicate ID: {dup_id}")
            logger.info(f"    Existing ID:  {existing_id}")
            logger.info(f"    Target URL:   {target_url[:70]}...")
        
        if len(conflicts) > 3:
            logger.info(f"  ... and {len(conflicts) - 3} more")
        
        logger.info("")
        logger.info(f"  Action: {'WOULD DELETE' if dry_run else 'DELETING'} duplicate articles")
        logger.info("=" * 60)
        logger.info("")
        
        # Delete duplicate articles
        if not dry_run:
            duplicate_ids = [conf[0] for conf in conflicts]
            stmt = delete(articles_table).where(
                articles_table.c.id_article.in_(duplicate_ids)
            )
            
            with engine.connect() as conn:
                result = conn.execute(stmt)
                conn.commit()
                logger.info(f"✅ Deleted {result.rowcount} duplicate articles")
                logger.info("")
    else:
        logger.info("✅ No duplicates found")
        logger.info("")
    
    return safe_ids


def sanitize_and_update(engine, articles_table, malformed_articles, safe_ids, dry_run=False):
    """Sanitize URLs and update database (only safe IDs without duplicates)"""
    logger.info("🧹 Starting URL sanitization...")
    
    updated_count = 0
    unchanged_count = 0
    error_count = 0
    skipped_count = 0
    
    fetcher = ArticleContentFetcher()
    
    for article in malformed_articles:
        id_article = article.id_article
        original_url = article.url
        title = article.title
        
        # Skip if this was marked as duplicate
        if id_article not in safe_ids:
            skipped_count += 1
            continue
        
        try:
            # Sanitize URL
            sanitized_url = fetcher.sanitize_url(original_url)
            
            if sanitized_url != original_url:
                logger.info(f"  [{id_article[:30]}...] {original_url[:80]}...")
                logger.info(f"           -> {sanitized_url[:80]}...")
                
                if not dry_run:
                    # Update database
                    stmt = update(articles_table).where(
                        articles_table.c.id_article == id_article
                    ).values(url=sanitized_url)
                    
                    with engine.connect() as conn:
                        conn.execute(stmt)
                        conn.commit()
                
                updated_count += 1
            else:
                unchanged_count += 1
                
        except Exception as e:
            logger.error(f"  ❌ Error processing article {id_article}: {e}")
            error_count += 1
    
    return updated_count, unchanged_count, error_count, skipped_count


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(description='Sanitize article URLs in database')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be updated without making changes')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit number of articles to process (for testing)')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize database
    db_path = get_db_path()
    logger.info(f"📊 Database: {db_path}")
    
    engine = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30}
    )
    
    meta = MetaData()
    articles_table = Table('gm_articles', meta, autoload_with=engine)
    
    # Find malformed URLs
    malformed_articles = find_malformed_urls(engine, articles_table)
    
    if not malformed_articles:
        logger.info("✅ No malformed URLs found!")
        return 0
    
    # Apply limit if specified
    if args.limit:
        malformed_articles = malformed_articles[:args.limit]
        logger.info(f"📋 Processing first {args.limit} articles (limit applied)")
    
    # Find and remove duplicates
    safe_ids = find_and_remove_duplicates(engine, articles_table, malformed_articles, args.dry_run)
    
    # Sanitize and update
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be made")
    
    updated, unchanged, errors, skipped = sanitize_and_update(
        engine, 
        articles_table, 
        malformed_articles,
        safe_ids,
        dry_run=args.dry_run
    )
    
    # Report
    logger.info("")
    logger.info("=" * 60)
    logger.info("📈 SANITIZATION REPORT")
    logger.info("=" * 60)
    logger.info(f"  Total scanned: {len(malformed_articles)}")
    if skipped > 0:
        logger.info(f"  🗑️  Duplicates removed: {skipped}")
    logger.info(f"  ✅ Updated: {updated}")
    logger.info(f"  ⏭️  Unchanged: {unchanged}")
    logger.info(f"  ❌ Errors: {errors}")
    logger.info("=" * 60)
    
    if args.dry_run:
        logger.info("ℹ️  This was a dry run. Use without --dry-run to apply changes.")
    
    return 0 if errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
