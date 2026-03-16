#!/usr/bin/env python3
"""
Fix articles with future publication dates caused by incorrect timezone handling.

This script:
1. Identifies sources with articles in the future
2. Suggests correct timezone based on source location
3. Updates source timezone and use_timezone flag
4. Recalculates published_at_gmt for affected articles
"""

import sys
import os
import argparse
import logging
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decouple import config
from sqlalchemy import create_engine, MetaData, Table, select, update, text, func

# Import timezone normalization from main collector
from wxAsyncNewsGather import normalize_timestamp_to_utc

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Known timezone offsets for common countries
TIMEZONE_FIXES = {
    # Colombia sources
    'La Opinión': 'UTC-05:00',
    'laopiniondemalaga': 'UTC+01:00',  # Spain
    'laopiniondezamora': 'UTC+01:00',  # Spain
    
    # US sources with wrong timezone
    'On3.com': 'UTC-05:00',  # Eastern Time (most likely)
    'New York Post': 'UTC-05:00',
    'WTOP': 'UTC-05:00',
    'Screen Rant': 'UTC-08:00',  # Pacific Time (most likely)
    'KGO-TV': 'UTC-08:00',  # San Francisco
    
    # Brazil sources
    'UOL Notícias': 'UTC-03:00',
    'Folha de S.Paulo': 'UTC-03:00',
    'IstoÉ': 'UTC-03:00',
    'Metrópoles': 'UTC-03:00',
    
    # Italy sources  
    'TGCom24': 'UTC+01:00',
    'Il Sole 24 Ore': 'UTC+01:00',
    
    # Argentina
    'CONTENIDOS.LANACION.COM.AR': 'UTC-03:00',
    'El Comercio': 'UTC-05:00',  # Peru
    
    # Australia
    'Sydney Morning Herald': 'UTC+11:00',
    'Daily Mail': 'UTC+00:00',  # UK
    
    # US Pacific Time
    'The Seattle Times': 'UTC-08:00',
}


def get_db_path():
    """Get database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(script_dir, db_path)
    return db_path


def find_sources_with_future_articles(engine, articles_table, sources_table):
    """Find sources that have articles with future dates."""
    logger.info("🔍 Scanning for sources with future articles...")
    
    stmt = select(
        sources_table.c.id_source,
        sources_table.c.name,
        sources_table.c.timezone,
        sources_table.c.use_timezone,
        func.count(articles_table.c.id_article).label('future_count')
    ).select_from(
        articles_table.join(sources_table, articles_table.c.id_source == sources_table.c.id_source)
    ).where(
        text("gm_articles.published_at_gmt > datetime('now')")
    ).group_by(
        sources_table.c.id_source
    ).order_by(
        text('future_count DESC')
    )
    
    with engine.connect() as conn:
        results = conn.execute(stmt).fetchall()
    
    logger.info(f"📊 Found {len(results)} sources with future articles")
    return results


def suggest_timezone_fix(source_name, current_tz):
    """Suggest correct timezone for a source."""
    if source_name in TIMEZONE_FIXES:
        return TIMEZONE_FIXES[source_name]
    return None


def update_source_timezone(engine, sources_table, source_id, new_timezone, enable_use_timezone):
    """Update source timezone configuration."""
    stmt = update(sources_table).where(
        sources_table.c.id_source == source_id
    ).values(
        timezone=new_timezone,
        use_timezone=1 if enable_use_timezone else 0
    )
    
    with engine.connect() as conn:
        conn.execute(stmt)
        conn.commit()


def recalculate_article_timestamps(engine, articles_table, source_id, source_name, source_timezone, dry_run=False):
    """Recalculate published_at_gmt for articles from this source."""
    # Get all articles from this source with publishedAt data
    stmt = select(
        articles_table.c.id_article,
        articles_table.c.publishedAt,
        articles_table.c.published_at_gmt
    ).where(
        articles_table.c.id_source == source_id
    ).where(
        articles_table.c.publishedAt.isnot(None)
    )
    
    with engine.connect() as conn:
        articles = conn.execute(stmt).fetchall()
    
    if not articles:
        return 0
    
    logger.info(f"  Found {len(articles)} articles to recalculate for {source_name}")
    
    fixed_count = 0
    for article in articles:
        try:
            # Recalculate using source timezone with use_timezone=True
            new_gmt, detected_tz = normalize_timestamp_to_utc(
                article.publishedAt,
                source_timezone=source_timezone,
                use_source_timezone=True
            )
            
            if new_gmt and new_gmt != article.published_at_gmt:
                if not dry_run:
                    update_stmt = update(articles_table).where(
                        articles_table.c.id_article == article.id_article
                    ).values(published_at_gmt=new_gmt)
                    
                    with engine.connect() as conn:
                        conn.execute(update_stmt)
                        conn.commit()
                
                fixed_count += 1
                
        except Exception as e:
            logger.debug(f"Error recalculating article {article.id_article}: {e}")
            continue
    
    return fixed_count


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(description='Fix articles with future publication dates')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be changed without making changes')
    parser.add_argument('--fix', action='store_true',
                       help='Apply fixes to database')
    parser.add_argument('--source', type=str,
                       help='Fix only specific source by name')
    
    args = parser.parse_args()
    
    # Initialize database
    db_path = get_db_path()
    logger.info(f"📊 Database: {db_path}")
    
    engine = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30}
    )
    
    meta = MetaData()
    articles_table = Table('gm_articles', meta, autoload_with=engine)
    sources_table = Table('gm_sources', meta, autoload_with=engine)
    
    # Find problematic sources
    problem_sources = find_sources_with_future_articles(engine, articles_table, sources_table)
    
    if not problem_sources:
        logger.info("✅ No sources with future articles found!")
        return 0
    
    # Analyze and suggest fixes
    logger.info("")
    logger.info("=" * 80)
    logger.info("📋 SOURCES WITH FUTURE ARTICLES")
    logger.info("=" * 80)
    
    fixes_to_apply = []
    
    for source in problem_sources:
        source_id = source.id_source
        source_name = source.name
        current_tz = source.timezone or 'None'
        use_tz = source.use_timezone
        future_count = source.future_count
        
        # Skip if filtering by source name
        if args.source and args.source.lower() not in source_name.lower():
            continue
        
        suggested_tz = suggest_timezone_fix(source_name, current_tz)
        
        logger.info(f"\n{source_name}")
        logger.info(f"  Future articles: {future_count}")
        logger.info(f"  Current timezone: {current_tz}")
        logger.info(f"  use_timezone: {use_tz}")
        
        if suggested_tz:
            logger.info(f"  ✅ Suggested fix: {suggested_tz} (use_timezone=1)")
            fixes_to_apply.append((source_id, source_name, suggested_tz))
        else:
            logger.info(f"  ⚠️  No automatic fix available (manual review needed)")
    
    # Apply fixes if requested
    if args.fix and fixes_to_apply:
        logger.info("")
        logger.info("=" * 80)
        logger.info("🔧 APPLYING FIXES")
        logger.info("=" * 80)
        
        for source_id, source_name, new_tz in fixes_to_apply:
            logger.info(f"\n{source_name}")
            logger.info(f"  Updating timezone to {new_tz}")
            
            if not args.dry_run:
                update_source_timezone(engine, sources_table, source_id, new_tz, True)
                logger.info(f"  ✅ Source timezone updated")
            
            logger.info(f"  Recalculating article timestamps...")
            fixed_count = recalculate_article_timestamps(
                engine, articles_table, source_id, source_name, new_tz, args.dry_run
            )
            logger.info(f"  ✅ Fixed {fixed_count} articles")
    
    logger.info("")
    logger.info("=" * 80)
    if args.dry_run:
        logger.info("ℹ️  This was a dry run. Use --fix to apply changes.")
    elif not args.fix:
        logger.info("ℹ️  No changes made. Use --fix to apply corrections.")
    logger.info("=" * 80)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
