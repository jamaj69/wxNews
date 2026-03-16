#!/usr/bin/env python3
"""
Fix timezone issues for sources with articles published in the future.

Process:
1. List sources with future articles
2. Verify RSS feeds to check if they're lying about timezone
3. Determine correct timezone based on country/location
4. Enable use_timezone=1
5. Backfill all articles from those sources
"""

import sys
import os
import argparse
import logging
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decouple import config
from sqlalchemy import create_engine, MetaData, Table, select, update, text, func
import feedparser
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Timezone mapping based on country/domain
TIMEZONE_MAP = {
    # US domains (most likely Eastern Time, but varies)
    '.com': {
        'On3.com': 'UTC-05:00',  # Sports site, likely Eastern
        'New York Post': 'UTC-05:00',
        'WTOP': 'UTC-05:00',  # Washington DC
        'Screen Rant': 'UTC-08:00',  # California
        'Buzzfeed': 'UTC-05:00',  # NYC
        'Heavy.com': 'UTC-05:00',
        'Page Six': 'UTC-05:00',  # NYC
        'Seeking Alpha': 'UTC-05:00',
        'TribLIVE': 'UTC-05:00',  # Pittsburgh
        'Metrópoles': 'UTC-03:00',  # Brazil (special case .com domain)
        'Variety': 'UTC-08:00',  # Los Angeles
        'Parade': 'UTC-05:00',  # NYC based
        'Mashable': 'UTC-08:00',  # San Francisco
        'IndieWire': 'UTC-05:00',  # NYC
        'Rolling Stone': 'UTC-05:00',  # NYC
        'Billboard': 'UTC-05:00',  # NYC
        'Ringside News': 'UTC-05:00',  # Wrestling news
        'Wrestling Inc.': 'UTC-05:00',
        'The Seattle Times': 'UTC-08:00',  # Seattle (special case .com)
        'CBS News': 'UTC-05:00',  # NYC
        'Clarín': 'UTC-03:00',  # Argentina (special case .com domain)
    },
    
    # Spain (.es domain)
    '.es': 'UTC+01:00',  # Spain (CET/CEST)
    
    # Colombia
    '.com.co': 'UTC-05:00',  # Colombia
    
    # Brazil
    '.com.br': 'UTC-03:00',  # Brazil
    '.br': 'UTC-03:00',
    
    # Argentina
    '.com.ar': 'UTC-03:00',  # Argentina
    '.ar': 'UTC-03:00',  # Clarín and others
    
    # Peru
    '.pe': 'UTC-05:00',  # Peru
    
    # Portugal
    '.pt': 'UTC+00:00',  # Portugal
    
    # UK
    '.co.uk': 'UTC+00:00',  # UK (GMT/BST)
    
    # Australia
    '.com.au': 'UTC+11:00',  # Australia East (AEDT)
    '.au': 'UTC+11:00',
    
    # Canada
    '.ca': 'UTC-05:00',  # Canada (varies, defaulting to Eastern)
    
    # India  
    '.in': 'UTC+05:30',  # India
    
    # Japan
    '.jp': 'UTC+09:00',  # Japan
    
    # Korea
    '.kr': 'UTC+09:00',  # Korea
    
    # Mexico
    '.mx': 'UTC-06:00',  # Mexico (varies, defaulting to Central)
    
    # Chile
    '.cl': 'UTC-03:00',  # Chile (varies with DST)
    
    # Nicaragua
    '.ni': 'UTC-06:00',  # Nicaragua
    
    # Guatemala
    '.gt': 'UTC-06:00',  # Guatemala
    
    # Uruguay
    '.uy': 'UTC-03:00',  # Uruguay
    
    # Israel
    '.il': 'UTC+02:00',  # Israel
    
    # Germany
    '.de': 'UTC+01:00',  # Germany
}

def get_db_path():
    """Get database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(script_dir, db_path)
    return db_path

def get_timezone_from_domain(url, source_name):
    """Determine timezone from domain and source name"""
    from urllib.parse import urlparse
    
    if not url:
        return None
    
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    # Check specific source names first
    for key, tz_map in TIMEZONE_MAP.items():
        if isinstance(tz_map, dict) and source_name in tz_map:
            return tz_map[source_name]
    
    # Check domain suffixes
    for suffix, tz in TIMEZONE_MAP.items():
        if isinstance(tz, str) and domain.endswith(suffix):
            return tz
    
    return None

def check_rss_feed(url, max_items=3):
    """
    Fetch RSS feed and check actual times used
    Returns: (sample_dates, has_timezone_info)
    """
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return None, False
        
        feed = feedparser.parse(response.content)
        dates = []
        has_tz_info = False
        
        for entry in feed.entries[:max_items]:
            if hasattr(entry, 'published'):
                dates.append(entry.published)
                # Check if timezone info is present (not just +0000)
                if '+' in entry.published or '-' in entry.published:
                    if not entry.published.endswith('+0000') and not entry.published.endswith('GMT'):
                        has_tz_info = True
        
        return dates, has_tz_info
        
    except Exception as e:
        logger.debug(f"Error checking RSS {url}: {e}")
        return None, False

def main():
    parser = argparse.ArgumentParser(description='Fix timezone issues in sources')
    parser.add_argument('--check-feeds', action='store_true', 
                       help='Check RSS feeds to verify timezone info')
    parser.add_argument('--apply-fixes', action='store_true',
                       help='Apply timezone fixes to database')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit number of sources to process')
    
    args = parser.parse_args()
    
    # Database setup
    db_path = get_db_path()
    logger.info(f"📊 Database: {db_path}")
    
    engine = create_engine(f'sqlite:///{db_path}', connect_args={'timeout': 30})
    meta = MetaData()
    sources_table = Table('gm_sources', meta, autoload_with=engine)
    articles_table = Table('gm_articles', meta, autoload_with=engine)
    
    # Find sources with future articles
    logger.info("🔍 Finding sources with future articles...")
    
    stmt = select(
        sources_table.c.id_source,
        sources_table.c.name,
        sources_table.c.url,
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
    
    if args.limit:
        stmt = stmt.limit(args.limit)
    
    with engine.connect() as conn:
        problem_sources = conn.execute(stmt).fetchall()
    
    logger.info(f"Found {len(problem_sources)} sources with future articles\n")
    
    # Analyze each source
    fixes = []
    
    for source in problem_sources:
        id_source = source.id_source
        name = source.name  
        url = source.url
        current_tz = source.timezone
        use_tz = source.use_timezone
        future_count = source.future_count
        
        logger.info(f"{'='*80}")
        logger.info(f"Source: {name}")
        logger.info(f"  URL: {url}")
        logger.info(f"  Current TZ: {current_tz}")
        logger.info(f"  use_timezone: {use_tz}")
        logger.info(f"  Future articles: {future_count}")
        
        # Determine correct timezone
        suggested_tz = get_timezone_from_domain(url, name)
        
        if suggested_tz:
            logger.info(f"  ✅ Suggested TZ: {suggested_tz}")
            fixes.append((id_source, name, suggested_tz, future_count))
        else:
            logger.info(f"  ⚠️  No timezone mapping found")
        
        # Check RSS feed if requested
        if args.check_feeds and url:
            logger.info(f"  📡 Checking RSS feed...")
            dates, has_tz = check_rss_feed(url)
            if dates:
                logger.info(f"     Sample dates: {dates[0] if dates else 'None'}")
                logger.info(f"     Has TZ info: {has_tz}")
        
        logger.info("")
    
    # Apply fixes if requested
    if args.apply_fixes and fixes:
        logger.info(f"\n{'='*80}")
        logger.info("🔧 APPLYING FIXES")
        logger.info(f"{'='*80}\n")
        
        for id_source, name, new_tz, future_count in fixes:
            logger.info(f"{name}")
            logger.info(f"  Setting timezone to {new_tz}")
            logger.info(f"  Enabling use_timezone=1")
            
            # Update source
            stmt = update(sources_table).where(
                sources_table.c.id_source == id_source
            ).values(
                timezone=new_tz,
                use_timezone=1
            )
            
            with engine.begin() as conn:
                conn.execute(stmt)
            
            logger.info(f"  ✅ Updated {name}\n")
        
        logger.info(f"\n✅ Fixed {len(fixes)} sources")
        logger.info("\n⚠️  Next step: Run backfill script to recalculate article timestamps")
    
    elif fixes:
        logger.info(f"\n{'='*80}")
        logger.info(f"Summary: {len(fixes)} sources need timezone fixes")
        logger.info("Run with --apply-fixes to update database")
        logger.info(f"{'='*80}")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
