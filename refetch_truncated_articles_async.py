#!/usr/bin/env python3
"""
Async version: Re-fetch truncated articles from URLs and update database.
Processes articles concurrently with proper timeout handling.
"""

import asyncio
import aiohttp
import aiosqlite
import sys
import html
import argparse
from html.parser import HTMLParser
from decouple import config
import logging
from typing import Optional, Dict, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
DB_PATH = str(config('DB_PATH', default='predator_news.db'))

# Concurrent processing settings
CONCURRENT_REQUESTS = 20  # Process 20 articles at a time
REQUEST_TIMEOUT = 8  # Timeout per article fetch (seconds)
BATCH_SIZE = 100  # Process database in batches of 100


class HTMLContentSanitizer(HTMLParser):
    """
    Custom HTML parser to sanitize article content.
    - Removes unwanted tags (script, style, head, meta, link, noscript)
    - Removes wrapper tags but keeps content (html, body, div, span)
    - Keeps content tags (p, br, img, a, b, i, strong, em, u, h1-h6, ul, ol, li)
    - Removes unwanted attributes (class, id, style, onclick, etc.)
    - Keeps essential attributes: img[src, alt], a[href]
    - Filters out long alt/title texts (>100 chars)
    """
    
    # Tags to completely skip (including their content)
    SKIP_TAGS = {'script', 'style', 'head', 'meta', 'link', 'noscript'}
    
    # Tags to ignore but keep their content
    WRAPPER_TAGS = {'html', 'body', 'div', 'span'}
    
    # Tags to keep with their content
    KEEP_TAGS = {'p', 'br', 'img', 'a', 'b', 'i', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code'}
    
    # Attributes to completely remove
    REMOVE_ATTRS = {'class', 'id', 'style', 'onclick', 'onload', 'onerror', 'onmouseover', 'onmouseout', 'onfocus', 'onblur'}
    
    # Attributes to keep per tag
    KEEP_ATTRS = {
        'img': {'src', 'alt'},
        'a': {'href'}
    }
    
    def __init__(self):
        super().__init__()
        self.result = []
        self.skip_level = 0  # Track nesting level of skipped tags
        
    def handle_starttag(self, tag, attrs):
        # Skip tags and their content
        if tag in self.SKIP_TAGS:
            self.skip_level += 1
            return
        
        # If we're inside a skipped tag, ignore everything
        if self.skip_level > 0:
            return
        
        # Ignore wrapper tags but keep processing their content
        if tag in self.WRAPPER_TAGS:
            return
        
        # Keep specific tags
        if tag in self.KEEP_TAGS:
            # Build the opening tag with filtered attributes
            filtered_attrs = []
            keep_attrs = self.KEEP_ATTRS.get(tag, set())
            
            for attr_name, attr_value in attrs:
                # Remove unwanted attributes
                if attr_name in self.REMOVE_ATTRS:
                    continue
                
                # Keep only allowed attributes for this tag
                if attr_name in keep_attrs:
                    # Filter long alt/title texts (e.g., photo captions)
                    if attr_name in {'alt', 'title'} and attr_value and len(attr_value) > 100:
                        continue
                    if attr_value is not None:
                        filtered_attrs.append(f'{attr_name}="{html.escape(attr_value, quote=True)}"')
            
            # Build the tag
            if filtered_attrs:
                self.result.append(f'<{tag} {" ".join(filtered_attrs)}>')
            else:
                self.result.append(f'<{tag}>')
    
    def handle_endtag(self, tag):
        # Handle skip tags
        if tag in self.SKIP_TAGS:
            self.skip_level = max(0, self.skip_level - 1)
            return
        
        # If we're inside a skipped tag, ignore everything
        if self.skip_level > 0:
            return
        
        # Ignore wrapper tags
        if tag in self.WRAPPER_TAGS:
            return
        
        # Close kept tags
        if tag in self.KEEP_TAGS:
            # Don't close self-closing tags
            if tag not in {'br', 'img'}:
                self.result.append(f'</{tag}>')
    
    def handle_data(self, data):
        # If we're inside a skipped tag, ignore the content
        if self.skip_level > 0:
            return
        
        # Keep the text content (preserve whitespace structure)
        if data:
            self.result.append(html.escape(data))
    
    def handle_startendtag(self, tag, attrs):
        """Handle self-closing tags like <br/> or <img/>"""
        self.handle_starttag(tag, attrs)
    
    def get_sanitized_html(self):
        """Return the sanitized HTML."""
        return ''.join(self.result)


def sanitize_html_content(html_content: str) -> str:
    """
    Sanitize HTML content by removing unwanted tags and attributes.
    
    Args:
        html_content: Raw HTML string
        
    Returns:
        Sanitized HTML string
    """
    if not html_content:
        return ""
    
    try:
        # Unescape HTML entities first (e.g., &lt; → <)
        unescaped = html.unescape(html_content)
        
        # Parse and sanitize
        parser = HTMLContentSanitizer()
        parser.feed(unescaped)
        parser.close()  # Important: closes the parser properly
        
        sanitized = parser.get_sanitized_html()
        
        # Clean up excessive whitespace
        sanitized = sanitized.strip()
        
        return sanitized
    except Exception as e:
        logger.warning(f"Error sanitizing HTML: {e}")
        return html_content


def extract_first_image_url(html_content: str) -> Optional[str]:
    """
    Extract the first <img> tag's src attribute from HTML content.
    
    Args:
        html_content: HTML string
        
    Returns:
        Image URL if found, None otherwise
    """
    if not html_content:
        return None
    
    try:
        # Simple regex to find first img src
        import re
        match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        if match:
            return match.group(1)
    except Exception as e:
        logger.debug(f"Error extracting image: {e}")
    
    return None


def extract_and_remove_first_image(html_content: str) -> Tuple[Optional[str], str]:
    """
    Extract the first image URL from HTML and remove that image tag.
    
    Args:
        html_content: HTML string
        
    Returns:
        Tuple of (image_url, cleaned_html)
    """
    if not html_content:
        return None, html_content
    
    try:
        import re
        # Try to find first img tag with src
        match = re.search(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', html_content, re.IGNORECASE)
        if match:
            url = match.group(1)
            # Only process if it's a valid HTTP(S) URL
            if url.startswith(('http://', 'https://')):
                # Remove the first img tag from HTML
                cleaned_html = html_content[:match.start()] + html_content[match.end():]
                return url, cleaned_html
    except Exception as e:
        logger.debug(f"Error extracting/removing image: {e}")
    
    return None, html_content



async def fetch_article_content_async(session: aiohttp.ClientSession, url: str, timeout: int = REQUEST_TIMEOUT) -> Dict:
    """
    Async fetch article content from URL using aiohttp.
    
    Returns dict with:
    - content: Article content
    - description: Article description
    - success: Boolean
    """
    result = {
        'content': None,
        'description': None,
        'success': False,
        'error': None
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.8,en-US;q=0.5,en;q=0.3',
    }
    
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            if response.status != 200:
                result['error'] = f"HTTP {response.status}"
                return result
            
            # Try to read content with proper encoding handling
            try:
                # First try with response's declared encoding
                html_content = await response.text()
            except UnicodeDecodeError:
                # If that fails, try reading as bytes and decode with fallback encodings
                try:
                    content_bytes = await response.read()
                    # Try common encodings
                    for encoding in ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']:
                        try:
                            html_content = content_bytes.decode(encoding)
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue
                    else:
                        # If all fail, use utf-8 with error handling
                        html_content = content_bytes.decode('utf-8', errors='ignore')
                except Exception as e:
                    result['error'] = f"Encoding error: {str(e)[:30]}"
                    return result
            
            # Try to extract content using BeautifulSoup
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Remove unwanted tags
                for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                    tag.decompose()
                
                # Try to find main content
                main_content = None
                
                # Common content containers
                for selector in ['article', 'main', '[class*="content"]', '[class*="article"]', 'body']:
                    main_content = soup.find(selector)
                    if main_content:
                        break
                
                if main_content:
                    # Get all paragraphs
                    paragraphs = main_content.find_all('p')
                    if paragraphs:
                        # Take first few paragraphs as description
                        description_parts = []
                        content_parts = []
                        
                        for i, p in enumerate(paragraphs[:10]):  # First 10 paragraphs
                            text = p.get_text(strip=True)
                            if len(text) > 20:  # Skip very short paragraphs
                                content_parts.append(str(p))
                                if i < 3:  # First 3 paragraphs for description
                                    description_parts.append(text)
                        
                        if content_parts:
                            result['content'] = ' '.join(content_parts)
                            result['description'] = ' '.join(description_parts)
                            result['success'] = True
                
            except Exception as e:
                logger.debug(f"BeautifulSoup parsing failed for {url}: {e}")
            
            # If parsing failed, try simple approach
            if not result['success'] and html_content:
                # Just return first 2000 chars of HTML as fallback
                result['content'] = html_content[:2000]
                result['description'] = html_content[:500]
                result['success'] = True
            
            return result
            
    except asyncio.TimeoutError:
        result['error'] = "Timeout"
        return result
    except aiohttp.ClientError as e:
        result['error'] = f"Client error: {str(e)[:50]}"
        return result
    except Exception as e:
        result['error'] = f"Error: {str(e)[:50]}"
        return result


async def find_truncated_articles(db_path: str) -> List[Tuple]:
    """
    Find articles with truncated descriptions.
    
    Returns list of tuples: (id_article, title, url, description, urlToImage)
    """
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        
        query = """
        SELECT id_article, title, description, url, urlToImage, content
        FROM gm_articles
        WHERE LENGTH(description) = 500 
           OR (description LIKE '%</%' AND description NOT LIKE '%</%>')
        ORDER BY id_article DESC
        """
        
        async with conn.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [(row[0], row[1], row[2], row[3], row[4], row[5]) for row in rows]


async def refetch_and_update_article(
    session: aiohttp.ClientSession,
    db_path: str,
    article: Tuple,
    progress: int,
    total: int
) -> Dict:
    """
    Re-fetch article from URL and update database.
    
    Args:
        session: aiohttp session
        db_path: Database path
        article: Tuple (id, title, description, url, urlToImage, content)
        progress: Current article number
        total: Total articles
        
    Returns:
        Dict with status info
    """
    id_article, title, old_description, url, old_url_to_image, old_content = article
    
    # Truncate title for display
    display_title = title[:60] + "..." if len(title) > 60 else title
    
    result = {
        'id': id_article,
        'title': display_title,
        'success': False,
        'updated': False,
        'error': None
    }
    
    try:
        # Fetch from URL
        fetched = await fetch_article_content_async(session, url)
        
        if not fetched['success']:
            result['error'] = fetched.get('error', 'Failed to fetch')
            return result
        
        result['success'] = True
        
        # Prepare updates
        updates = {}
        
        # Sanitize and update description if we got new content
        if fetched['description']:
            new_description = sanitize_html_content(fetched['description'])
            if new_description and len(new_description) > len(old_description):
                updates['description'] = new_description
        
        # Sanitize and update content
        if fetched['content']:
            new_content = sanitize_html_content(fetched['content'])
            if new_content:
                updates['content'] = new_content
        
        # Extract image if urlToImage is empty and remove it from HTML to avoid duplicates
        if not old_url_to_image:
            image_url = None
            # Try from new description first
            if 'description' in updates:
                image_url, cleaned_desc = extract_and_remove_first_image(updates['description'])
                if image_url:
                    updates['description'] = cleaned_desc  # Update with cleaned HTML
            # Try from new content if no image found in description
            if not image_url and 'content' in updates:
                image_url, cleaned_content = extract_and_remove_first_image(updates['content'])
                if image_url:
                    updates['content'] = cleaned_content  # Update with cleaned HTML
            
            if image_url:
                updates['urlToImage'] = image_url
        
        # Update database if we have changes
        if updates:
            async with aiosqlite.connect(db_path) as conn:
                set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
                query = f"UPDATE gm_articles SET {set_clause} WHERE id_article = ?"
                values = list(updates.values()) + [id_article]
                
                await conn.execute(query, values)
                await conn.commit()
                
                result['updated'] = True
                result['changes'] = len(updates)
        
        return result
        
    except Exception as e:
        result['error'] = str(e)[:50]
        return result


async def process_batch(
    session: aiohttp.ClientSession,
    db_path: str,
    articles: List[Tuple],
    start_idx: int,
    total: int
) -> Tuple[int, int]:
    """
    Process a batch of articles concurrently.
    
    Returns: (success_count, failed_count)
    """
    tasks = []
    for i, article in enumerate(articles):
        progress = start_idx + i + 1
        task = refetch_and_update_article(session, db_path, article, progress, total)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success_count = 0
    failed_count = 0
    
    for i, result in enumerate(results):
        progress = start_idx + i + 1
        
        if isinstance(result, Exception):
            failed_count += 1
            logger.error(f"[{progress}/{total}] ❌ Exception: {str(result)[:50]}")
        elif isinstance(result, dict):
            if result['updated']:
                success_count += 1
                logger.info(f"[{progress}/{total}] ✅ {result['title']}")
            elif result['success']:
                logger.info(f"[{progress}/{total}] ℹ️  {result['title']} (no changes)")
            else:
                failed_count += 1
                error_msg = result.get('error', 'Unknown')
                logger.warning(f"[{progress}/{total}] ❌ {result['title']} - {error_msg}")
        else:
            failed_count += 1
            logger.error(f"[{progress}/{total}] ❌ Unexpected result type: {type(result)}")
    
    return success_count, failed_count


async def main():
    """Main async function."""
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Re-fetch truncated articles from URLs')
    parser.add_argument('-y', '--yes', action='store_true',
                        help='Skip confirmation prompt and start immediately')
    args = parser.parse_args()
    
    print(f"📊 Connecting to database: {DB_PATH}\n")
    
    # Find truncated articles
    print("🔍 Finding truncated articles...")
    articles = await find_truncated_articles(DB_PATH)
    total = len(articles)
    
    print(f"Found {total} truncated articles\n")
    
    if total == 0:
        print("✅ No truncated articles found!")
        return 0
    
    # Ask for confirmation unless --yes flag is provided
    if not args.yes:
        response = input(f"Re-fetch and update these {total} articles? [y/N]: ").strip().lower()
        if response != 'y':
            print("❌ Cancelled")
            return 1
    
    print(f"\n🚀 Starting async re-fetch process...")
    print(f"⚙️  Settings: {CONCURRENT_REQUESTS} concurrent requests, {REQUEST_TIMEOUT}s timeout per request\n")
    
    total_success = 0
    total_failed = 0
    
    # Create aiohttp session with connection pooling
    connector = aiohttp.TCPConnector(limit=CONCURRENT_REQUESTS, limit_per_host=5)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Process in batches
        for i in range(0, total, CONCURRENT_REQUESTS):
            batch = articles[i:i + CONCURRENT_REQUESTS]
            success, failed = await process_batch(session, DB_PATH, batch, i, total)
            total_success += success
            total_failed += failed
            
            # Small delay between batches to be nice to servers
            if i + CONCURRENT_REQUESTS < total:
                await asyncio.sleep(0.5)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"📊 Summary:")
    print(f"   ✅ Successfully updated: {total_success}")
    print(f"   ❌ Failed: {total_failed}")
    print(f"   ℹ️  No changes needed: {total - total_success - total_failed}")
    print(f"{'='*60}\n")
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
