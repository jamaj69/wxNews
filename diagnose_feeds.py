#!/usr/bin/env python3
"""
Diagnose problematic RSS feeds to understand what's happening.
"""

import asyncio
import aiohttp
import feedparser
import sqlite3
import sys
from urllib.parse import urlparse
from typing import Dict, List

DB_PATH = 'predator_news.db'

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9,es;q=0.8,pt;q=0.7',
    'Accept-Encoding': 'gzip, deflate',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
}

async def test_feed(session: aiohttp.ClientSession, name: str, url: str) -> Dict:
    """Test a single feed and return diagnostic info."""
    result = {
        'name': name,
        'url': url,
        'status': None,
        'error': None,
        'content_type': None,
        'redirect': None,
        'is_valid_feed': False,
        'entries_count': 0,
        'recommendations': []
    }
    
    try:
        # Try with browser headers
        async with session.get(url, headers=BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as response:
            result['status'] = response.status
            result['content_type'] = response.headers.get('Content-Type', '')
            
            if str(response.url) != url:
                result['redirect'] = str(response.url)
            
            if response.status == 200:
                content = await response.text()
                
                # Try to parse with feedparser
                feed = feedparser.parse(content)
                
                if feed.bozo == 0 or len(feed.entries) > 0:
                    result['is_valid_feed'] = True
                    result['entries_count'] = len(feed.entries)
                else:
                    result['recommendations'].append(f"Feed parse error: {feed.bozo_exception if hasattr(feed, 'bozo_exception') else 'Unknown'}")
                
                # Check if it looks like HTML instead of RSS
                if content.strip().lower().startswith('<!doctype html') or '<html' in content[:300].lower():
                    result['recommendations'].append("URL returns HTML instead of RSS feed")
            
            elif response.status == 403:
                result['recommendations'].append("HTTP 403: Site is blocking requests (anti-bot protection)")
                result['recommendations'].append("Try: Different User-Agent, add Referer header, or contact site")
                
            elif response.status == 404:
                result['recommendations'].append("HTTP 404: Feed URL no longer exists")
                result['recommendations'].append("Try: Check site homepage for new RSS link")
                
            elif response.status == 301 or response.status == 302:
                result['recommendations'].append(f"Redirected to: {result['redirect']}")
            
            elif response.status >= 500:
                result['recommendations'].append(f"HTTP {response.status}: Server error (temporary issue)")
                
    except asyncio.TimeoutError:
        result['error'] = "Timeout (>20s)"
        result['recommendations'].append("Site is too slow or blocking")
        result['recommendations'].append("Try: Increase timeout or check if site moved")
        
    except aiohttp.ClientConnectorError as e:
        result['error'] = f"Connection error: {str(e)}"
        result['recommendations'].append("DNS/SSL issue - site may be down or domain expired")
        
    except Exception as e:
        result['error'] = f"{type(e).__name__}: {str(e)}"
        result['recommendations'].append(f"Unexpected error: {type(e).__name__}")
    
    return result


async def check_alternative_feeds(session: aiohttp.ClientSession, base_url: str) -> List[str]:
    """Try to find alternative RSS feed URLs."""
    parsed = urlparse(base_url)
    domain = f"{parsed.scheme}://{parsed.netloc}"
    
    alternatives = [
        f"{domain}/feed/",
        f"{domain}/rss/",
        f"{domain}/feed",
        f"{domain}/rss",
        f"{domain}/feeds/",
        f"{domain}/index.xml",
        f"{domain}/atom.xml",
        f"{domain}/rss.xml",
    ]
    
    found = []
    for alt_url in alternatives:
        if alt_url == base_url:
            continue
        try:
            async with session.head(alt_url, headers=BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True) as response:
                if response.status == 200:
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'xml' in content_type or 'rss' in content_type or 'atom' in content_type:
                        found.append(alt_url)
        except:
            pass
    
    return found


async def diagnose_feeds(source_names: List[str]):
    """Diagnose a list of feeds."""
    # Get feeds from database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    feeds_to_test = []
    for name in source_names:
        cursor.execute("""
            SELECT name, url
            FROM gm_sources
            WHERE LOWER(name) LIKE LOWER(?)
            LIMIT 1
        """, (f'%{name}%',))
        
        result = cursor.fetchone()
        if result:
            feeds_to_test.append(result)
        else:
            print(f"⚠️  Not found in database: {name}\n")
    
    conn.close()
    
    if not feeds_to_test:
        print("❌ No feeds found to test")
        return
    
    print(f"\n🔍 Diagnosing {len(feeds_to_test)} feeds...")
    print("=" * 100)
    
    async with aiohttp.ClientSession() as session:
        for name, url in feeds_to_test:
            print(f"\n📡 Testing: {name}")
            print(f"   URL: {url}")
            
            result = await test_feed(session, name, url)
            
            # Status
            if result['status']:
                status_emoji = "✅" if result['status'] == 200 else "❌"
                print(f"   {status_emoji} HTTP Status: {result['status']}")
            
            if result['error']:
                print(f"   ❌ Error: {result['error']}")
            
            if result['content_type']:
                print(f"   📄 Content-Type: {result['content_type']}")
            
            if result['redirect']:
                print(f"   ↪️  Redirected to: {result['redirect']}")
            
            if result['is_valid_feed']:
                print(f"   ✅ Valid RSS feed with {result['entries_count']} entries")
            
            # Recommendations
            if result['recommendations']:
                print(f"   💡 Recommendations:")
                for rec in result['recommendations']:
                    print(f"      • {rec}")
            
            # Try to find alternatives if current feed failed
            if result['status'] != 200 or not result['is_valid_feed']:
                print(f"   🔎 Searching for alternative feeds...")
                alternatives = await check_alternative_feeds(session, url)
                if alternatives:
                    print(f"   ✨ Found {len(alternatives)} alternative(s):")
                    for alt in alternatives:
                        print(f"      • {alt}")
                else:
                    print(f"   ⚠️  No alternatives found")
            
            print("-" * 100)
    
    print("\n✅ Diagnosis complete")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("""
Usage:
  python3 diagnose_feeds.py <source_name1> <source_name2> ...

Examples:
  python3 diagnose_feeds.py "TecnoGaming" "Computer Hoy"
  python3 diagnose_feeds.py "Alt1040" "MuyComputer" "MuyLinux"
        """)
        sys.exit(1)
    
    source_names = sys.argv[1:]
    asyncio.run(diagnose_feeds(source_names))
