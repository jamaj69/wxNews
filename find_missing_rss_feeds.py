#!/usr/bin/env python3
"""
Find RSS feeds for technology sources that only have NewsAPI entries.
"""

import asyncio
import aiohttp
import feedparser
import logging
from sqlalchemy import create_engine, MetaData, Table, select
from sqlalchemy.dialects.sqlite import insert
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Sources that need RSS feeds
SOURCES_TO_CHECK = [
    {'id': 'crypto-coins-news', 'name': 'Crypto Coins News', 'url': 'https://www.ccn.com'},
    {'id': 'gruenderszene', 'name': 'Gruenderszene', 'url': 'http://www.gruenderszene.de'},
    {'id': 'recode', 'name': 'Recode', 'url': 'http://www.recode.net'},
    {'id': 't3n', 'name': 'T3n', 'url': 'https://t3n.de'},
    {'id': 'techcrunch-cn', 'name': 'TechCrunch (CN)', 'url': 'https://techcrunch.cn'},
    {'id': 'wired-de', 'name': 'Wired.de', 'url': 'https://www.wired.de'},
]


async def try_rss_url(session, url, source_name):
    """Try a URL and check if it's a valid RSS feed"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True) as response:
            if response.status == 200:
                content = await response.text()
                
                # Quick check for RSS/Atom markers
                if any(tag in content[:2000] for tag in ['<rss', '<feed', '<channel', '<atom']):
                    # Validate with feedparser
                    feed = feedparser.parse(content)
                    if feed.entries or (hasattr(feed, 'feed') and hasattr(feed.feed, 'title')):
                        feed_title = getattr(feed.feed, 'title', source_name)
                        logger.info(f"    ✅ VALID RSS: {url}")
                        logger.info(f"       Feed title: {feed_title}")
                        logger.info(f"       Entries: {len(feed.entries)}")
                        return {
                            'url': url,
                            'title': feed_title,
                            'entries': len(feed.entries)
                        }
    except:
        pass
    return None


async def find_rss_in_html(session, base_url):
    """Parse HTML to find RSS feed links"""
    try:
        async with session.get(base_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                return []
            
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            rss_links = []
            
            # Look for <link> tags with RSS/Atom
            for link in soup.find_all('link', type=['application/rss+xml', 'application/atom+xml']):
                href = link.get('href')
                if href:
                    if href.startswith('http'):
                        rss_links.append(href)
                    elif href.startswith('//'):
                        rss_links.append('https:' + href)
                    elif href.startswith('/'):
                        from urllib.parse import urlparse
                        parsed = urlparse(base_url)
                        rss_links.append(f"{parsed.scheme}://{parsed.netloc}{href}")
                    else:
                        rss_links.append(base_url.rstrip('/') + '/' + href.lstrip('/'))
            
            # Look for <a> tags with RSS/feed keywords
            for link in soup.find_all('a', href=True):
                href = link.get('href', '').lower()
                text = link.get_text('', strip=True).lower()
                
                if any(keyword in href or keyword in text for keyword in ['rss', 'feed', 'atom']):
                    full_url = href
                    if href.startswith('http'):
                        rss_links.append(href)
                    elif href.startswith('//'):
                        rss_links.append('https:' + href)
                    elif href.startswith('/'):
                        from urllib.parse import urlparse
                        parsed = urlparse(base_url)
                        rss_links.append(f"{parsed.scheme}://{parsed.netloc}{href}")
            
            return list(set(rss_links))  # Remove duplicates
    except:
        return []


async def discover_rss_feed(session, source):
    """Try multiple methods to discover RSS feed"""
    source_id = source['id']
    source_name = source['name']
    base_url = source['url']
    
    logger.info(f"\n{'='*80}")
    logger.info(f"Searching RSS for: {source_name}")
    logger.info(f"  Base URL: {base_url}")
    
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    domain = parsed.netloc
    scheme = parsed.scheme or 'https'
    
    # Common RSS paths to try
    common_paths = [
        '/feed',
        '/rss',
        '/feed/',
        '/rss/',
        '/feeds',
        '/rss.xml',
        '/feed.xml',
        '/atom.xml',
        '/index.xml',
        '/?feed=rss2',
        '/?feed=rss',
        '/blog/feed',
        '/feed/rss',
        '/posts/rss',
        '/.rss',
    ]
    
    # Try common paths first
    logger.info(f"  Trying common RSS paths...")
    for path in common_paths:
        test_url = f"{scheme}://{domain}{path}"
        result = await try_rss_url(session, test_url, source_name)
        if result:
            return result
    
    # Try parsing HTML for RSS links
    logger.info(f"  Parsing HTML for RSS links...")
    rss_links = await find_rss_in_html(session, base_url)
    
    if rss_links:
        logger.info(f"  Found {len(rss_links)} potential RSS links in HTML")
        for rss_url in rss_links[:10]:  # Limit to 10
            logger.info(f"    Checking: {rss_url}")
            result = await try_rss_url(session, rss_url, source_name)
            if result:
                return result
    
    logger.info(f"  ❌ No RSS feed found for {source_name}")
    return None


async def main():
    """Main function to find RSS feeds and add them to database"""
    
    db_path = 'predator_news.db'
    eng = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False}
    )
    
    meta = MetaData()
    gm_sources = Table('gm_sources', meta, autoload_with=eng)
    
    results = []
    
    async with aiohttp.ClientSession(headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    }) as session:
        
        for source in SOURCES_TO_CHECK:
            result = await discover_rss_feed(session, source)
            if result:
                results.append({
                    'source': source,
                    'rss': result
                })
    
    # Summary
    logger.info(f"\n{'='*80}")
    logger.info("📊 DISCOVERY SUMMARY")
    logger.info(f"  Sources checked: {len(SOURCES_TO_CHECK)}")
    logger.info(f"  RSS feeds found: {len(results)}")
    logger.info(f"  Not found: {len(SOURCES_TO_CHECK) - len(results)}")
    
    if results:
        logger.info(f"\n✅ FOUND RSS FEEDS:")
        for item in results:
            source = item['source']
            rss = item['rss']
            logger.info(f"\n  {source['name']}")
            logger.info(f"    RSS URL: {rss['url']}")
            logger.info(f"    Feed Title: {rss['title']}")
            logger.info(f"    Entries: {rss['entries']}")
            
            # Add to database
            rss_id = f"rss-{source['id']}"
            
            # Get original source info for description, language, country
            with eng.connect() as conn:
                stmt = select(gm_sources).where(gm_sources.c.id_source == source['id'])
                original = conn.execute(stmt).fetchone()
                
                if original:
                    try:
                        ins = insert(gm_sources).values(
                            id_source=rss_id,
                            name=rss['title'],
                            description=original.description,
                            url=rss['url'],
                            category='technology',
                            language=original.language,
                            country=original.country
                        )
                        ins = ins.on_conflict_do_nothing()
                        result = conn.execute(ins)
                        conn.commit()
                        
                        if result.rowcount > 0:
                            logger.info(f"    ✅ Added to database as {rss_id}")
                        else:
                            logger.info(f"    ⚠️  Already exists in database")
                    except Exception as e:
                        logger.error(f"    ❌ Failed to add: {e}")
    
    logger.info("="*80)


if __name__ == '__main__':
    asyncio.run(main())
