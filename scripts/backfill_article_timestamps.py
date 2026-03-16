#!/usr/bin/env python3
"""
Backfill Article Timestamps

This script recalculates published_at_gmt for articles with future timestamps
using the corrected timezone settings from fix_timezone_sources.py.

Usage:
    python scripts/backfill_article_timestamps.py          # Dry-run (preview only)
    python scripts/backfill_article_timestamps.py --apply  # Apply changes

Author: Created 2026-03-16 to fix impossible future dates
"""

import sqlite3
import logging
import sys
import os
from datetime import datetime, timezone

# Add parent directory to path to import wxAsyncNewsGather
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the normalize_timestamp_to_utc function from wxAsyncNewsGather
try:
    from wxAsyncNewsGather import normalize_timestamp_to_utc
    logger_temp = logging.getLogger(__name__)
    logger_temp.info("✅ Successfully imported normalize_timestamp_to_utc from wxAsyncNewsGather")
except ImportError as e:
    print(f"❌ Failed to import normalize_timestamp_to_utc: {e}")
    print("Make sure wxAsyncNewsGather.py is in the parent directory")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = 'predator_news.db'


def backfill_timestamps(apply_changes: bool = False):
    """
    Recalculate published_at_gmt for articles with future timestamps.
    
    Args:
        apply_changes: If True, apply changes to database. If False, dry-run only.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Get articles with future timestamps and their source timezone info
        query = """
        SELECT 
            a.id_article,
            a.publishedAt,
            a.published_at_gmt,
            s.name as source_name,
            s.timezone,
            s.use_timezone
        FROM gm_articles a
        JOIN gm_sources s ON a.id_source = s.id_source
        WHERE a.published_at_gmt > datetime('now')
        ORDER BY a.published_at_gmt ASC
        """
        
        cursor.execute(query)
        articles = cursor.fetchall()
        
        logger.info(f"Found {len(articles)} articles with future timestamps")
        
        if len(articles) == 0:
            logger.info("✅ No articles to backfill!")
            return
        
        # Process each article
        fixed_count = 0
        error_count = 0
        still_future_count = 0
        
        # Show first 5 examples
        logger.info("\nFirst 5 examples:")
        for idx, article in enumerate(articles[:5]):
            id_article, publishedAt, published_at_gmt, source_name, timezone_str, use_timezone = article
            logger.info(f"\n{idx+1}. Article ID: {id_article}")
            logger.info(f"   Source: {source_name}")
            logger.info(f"   Original timestamp: {publishedAt}")
            logger.info(f"   Current published_at_gmt: {published_at_gmt}")
            logger.info(f"   Timezone: {timezone_str}, use_timezone: {use_timezone}")
        
        if not apply_changes:
            logger.info("\n⚠️  DRY-RUN MODE - No changes will be made")
            logger.info(f"⚠️  Run with --apply to apply changes to {len(articles)} articles")
            return
        
        # Apply changes
        logger.info("\n🔧 Applying changes...")
        logger.info("Using normalize_timestamp_to_utc() from wxAsyncNewsGather with updated logic")
        
        for article in articles:
            id_article, publishedAt, published_at_gmt, source_name, timezone_str, use_timezone = article
            
            # Use the same function as wxAsyncNewsGather
            # This now respects use_timezone=1 and forces source timezone
            new_published_at_gmt, detected_tz = normalize_timestamp_to_utc(
                publishedAt, 
                timezone_str, 
                use_source_timezone=(use_timezone == 1)
            )
            
            if new_published_at_gmt is None:
                error_count += 1
                logger.warning(f"❌ Failed to parse: Article {id_article} ({source_name}): {publishedAt}")
                continue
            
            # Parse to datetime to check if still in future
            try:
                new_dt = datetime.fromisoformat(new_published_at_gmt.replace('Z', '+00:00'))
            except:
                error_count += 1
                logger.warning(f"❌ Invalid datetime: Article {id_article} ({source_name}): {new_published_at_gmt}")
                continue
            
            # Check if still in future
            if new_dt > datetime.now(timezone.utc):
                still_future_count += 1
                if still_future_count <= 10:  # Only log first 10
                    logger.warning(f"⚠️  Still future: Article {id_article} ({source_name}): {new_published_at_gmt}")
            
            # Update database
            try:
                cursor.execute(
                    "UPDATE gm_articles SET published_at_gmt = ? WHERE id_article = ?",
                    (new_published_at_gmt, id_article)
                )
                fixed_count += 1
                
                if fixed_count % 100 == 0:
                    logger.info(f"Progress: {fixed_count}/{len(articles)} articles processed")
                    
            except Exception as e:
                error_count += 1
                logger.error(f"❌ Failed to update article {id_article}: {e}")
        
        # Commit changes
        conn.commit()
        
        # Final report
        logger.info("\n" + "="*60)
        logger.info("BACKFILL COMPLETE")
        logger.info("="*60)
        logger.info(f"Total articles processed: {len(articles)}")
        logger.info(f"✅ Successfully fixed: {fixed_count}")
        logger.info(f"❌ Errors: {error_count}")
        logger.info(f"⚠️  Still future: {still_future_count}")
        logger.info("="*60)
        
        # Verify final count
        cursor.execute("SELECT COUNT(*) FROM gm_articles WHERE published_at_gmt > datetime('now')")
        final_count = cursor.fetchone()[0]
        logger.info(f"\n🔍 Final verification: {final_count} articles still have future timestamps")
        
        if final_count > 0:
            logger.warning("\n⚠️  Some articles still have future timestamps!")
            logger.warning("This could be:")
            logger.warning("  1. Truly scheduled future content")
            logger.warning("  2. Sources without timezone mapping")
            logger.warning("  3. New articles collected while backfill was running")
            logger.warning("\nInvestigate with:")
            logger.warning("  sqlite3 predator_news.db \"SELECT s.name, COUNT(*) as count FROM gm_articles a JOIN gm_sources s ON a.id_source = s.id_source WHERE a.published_at_gmt > datetime('now') GROUP BY s.name ORDER BY count DESC LIMIT 10\"")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    """Main entry point."""
    # Check for --apply flag
    apply_changes = '--apply' in sys.argv
    
    if apply_changes:
        logger.info("🔧 APPLY MODE - Changes will be written to database")
    else:
        logger.info("👁️  DRY-RUN MODE - No changes will be made")
    
    # Run backfill
    backfill_timestamps(apply_changes)


if __name__ == '__main__':
    main()
