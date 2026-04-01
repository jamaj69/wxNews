#!/usr/bin/env python3
"""
Article content fetcher module.
Fetches missing article content, author, and publication time from article URLs.
"""

import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Playwright is used as a headless-browser fallback for JS-rendered pages.
try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    logger.debug("playwright not installed — headless fallback disabled")


class ArticleContentFetcher:
    """Fetch additional article content from URLs when RSS feed data is incomplete."""
    
    def __init__(self, timeout=10):
        self.timeout = timeout
        # Don't explicitly set Accept-Encoding - let requests handle it automatically
        # with gzip/deflate which works reliably. Explicit br/zstd can cause issues.
        self.default_headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'DNT': '1',
            'Sec-GPC': '1',
            'TE': 'trailers',
        }
    
    @staticmethod
    def sanitize_url(url):
        """
        Sanitize and normalize URL to fix common issues.
        
        - Remove double slashes in path (but preserve protocol://)
        - Remove redirect chain prefixes
        - Strip whitespace
        - Validate basic URL structure
        """
        if not url or not isinstance(url, str):
            return url
        
        # Strip whitespace
        url = url.strip()
        
        # Handle redirect chains (e.g., folha.com.br redirects)
        # Pattern: http://redirect.site/*http://actual.site
        if '*http://' in url or '*https://' in url:
            # Extract the actual target URL after the * marker
            if '*https://' in url:
                url = url.split('*https://', 1)[1]
                url = 'https://' + url
            elif '*http://' in url:
                url = url.split('*http://', 1)[1]
                url = 'http://' + url
        
        # Fix double slashes in path (but preserve protocol://)
        # Pattern: https://domain.com/path//with//double -> https://domain.com/path/with/double
        if '://' in url:
            protocol, rest = url.split('://', 1)
            # Replace multiple consecutive slashes with single slash
            rest = re.sub(r'/+', '/', rest)
            url = f'{protocol}://{rest}'
        
        return url
    
    def _get_headers_for_url(self, url):
        """Get appropriate headers for the given URL based on domain."""
        # NDTV Profit requires special User-Agent to avoid 403 errors
        if 'ndtvprofit.com' in url.lower():
            return {
                'User-Agent': 'FeedReader/1.0 (Linux)',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.ndtvprofit.com/',
                'Connection': 'keep-alive',
            }
        
        # Default headers for all other sites
        return self.default_headers.copy()
    
    def fetch(self, url):
        """
        Fetch article content from URL.
        
        Returns dict with:
        - author: Author name if found
        - published_time: Publication time if found
        - description: Article summary/description
        - content: First few paragraphs of article text
        - success: Boolean indicating if content was fetched
        - error_code: HTTP error code if request failed (403, 404, etc.)
        - sanitized_url: The sanitized URL used for fetching (if different from input)
        """
        result = {
            'author': None,
            'published_time': None,
            'description': None,
            'content': None,
            'success': False,
            'error_code': None,
            'sanitized_url': None
        }
        
        # Initialize sanitized_url to original URL (will be updated if sanitization changes it)
        sanitized_url = url
        
        try:
            # Sanitize URL to fix common issues
            sanitized_url = self.sanitize_url(url)
            
            # Track if URL was modified
            if sanitized_url != url:
                logger.info(f"URL sanitized: {url} -> {sanitized_url}")
                result['sanitized_url'] = sanitized_url
            
            # Basic URL validation
            if not sanitized_url or not sanitized_url.startswith(('http://', 'https://')):
                logger.warning(f"Invalid URL format: {url}")
                result['error_code'] = 'INVALID_URL'
                return result
            
            logger.debug(f"Fetching content from: {sanitized_url}")
            headers = self._get_headers_for_url(sanitized_url)
            response = requests.get(sanitized_url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            
            # Try to get text with proper encoding handling
            try:
                html_text = response.text
            except (UnicodeDecodeError, LookupError) as e:
                # If encoding detection fails, try common encodings
                logger.debug(f"Encoding error, trying fallback encodings: {e}")
                for encoding in ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']:
                    try:
                        html_text = response.content.decode(encoding)
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                else:
                    # Last resort: decode with error handling
                    html_text = response.content.decode('utf-8', errors='ignore')
            
            # Try lxml parser first (faster and more robust for most sites)
            # Fall back to html.parser if lxml fails
            soup = None
            for parser in ['lxml', 'html.parser']:
                try:
                    soup = BeautifulSoup(html_text, parser)
                    break
                except Exception as e:
                    if parser == 'html.parser':
                        # Both parsers failed, re-raise the exception
                        raise
                    logger.debug(f"Parser {parser} failed for {url}, trying next parser")
            
            if soup is None:
                raise Exception("All parsers failed")
            
            # Extract author
            result['author'] = self._extract_author(soup)
            
            # Extract publication time
            result['published_time'] = self._extract_time(soup)
            
            # Extract description
            result['description'] = self._extract_description(soup)
            
            # Extract content (first few paragraphs)
            result['content'] = self._extract_content(soup)
            
            result['success'] = True
            logger.debug(f"Successfully extracted content from {sanitized_url}")

            # ── Playwright fallback ──────────────────────────────────────────
            # If requests got a response but yielded no useful content, the page
            # is likely JS-rendered. Re-fetch with a real headless browser.
            if not self._has_useful_content(result) and _PLAYWRIGHT_AVAILABLE:
                logger.debug(f"No content from requests — retrying with headless browser: {sanitized_url}")
                pw_html = self._fetch_with_playwright(sanitized_url)
                if pw_html:
                    pw_soup = BeautifulSoup(pw_html, 'html.parser')
                    result['author'] = result['author'] or self._extract_author(pw_soup)
                    result['published_time'] = result['published_time'] or self._extract_time(pw_soup)
                    result['description'] = result['description'] or self._extract_description(pw_soup)
                    result['content'] = result['content'] or self._extract_content(pw_soup)
                    if self._has_useful_content(result):
                        logger.debug(f"Headless browser enrichment succeeded for {sanitized_url}")
            # ────────────────────────────────────────────────────────────────
            
        except requests.HTTPError as e:
            # Capture HTTP error code (403, 404, etc.)
            if e.response is not None:
                result['error_code'] = e.response.status_code
            logger.error(f"HTTP {result['error_code']} error for {sanitized_url}: {e}")
            # For bot-blocking errors (403/406), try headless browser
            if result['error_code'] in (403, 406) and _PLAYWRIGHT_AVAILABLE:
                logger.debug(f"HTTP {result['error_code']} — retrying with headless browser: {sanitized_url}")
                pw_html = self._fetch_with_playwright(sanitized_url)
                if pw_html:
                    pw_soup = BeautifulSoup(pw_html, 'html.parser')
                    result['author'] = self._extract_author(pw_soup)
                    result['published_time'] = self._extract_time(pw_soup)
                    result['description'] = self._extract_description(pw_soup)
                    result['content'] = self._extract_content(pw_soup)
                    if self._has_useful_content(result):
                        result['success'] = True
                        result['error_code'] = None
                        logger.debug(f"Headless browser recovered content after HTTP {e.response.status_code}")
        except requests.Timeout as e:
            # Connection or read timeout
            result['error_code'] = 'TIMEOUT'
            logger.warning(f"Timeout fetching {sanitized_url}: {e}")
        except requests.RequestException as e:
            result['error_code'] = 'REQUEST_ERROR'
            logger.error(f"Request error for {sanitized_url}: {e}")
        except Exception as e:
            result['error_code'] = 'PARSE_ERROR'
            logger.error(f"Parse error for {sanitized_url}: {e}")
        
        return result
    
    def _fetch_with_playwright(self, url):
        """
        Fetch page HTML using a headless Chromium browser.
        Used as fallback when requests returns a JS-rendered skeleton.
        Returns the rendered HTML string, or None on failure.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            return None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                               '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                    locale='pt-BR',
                    java_script_enabled=True,
                )
                page = context.new_page()
                # Block images/fonts to speed things up
                page.route('**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf}',
                           lambda route: route.abort())
                page.goto(url, wait_until='domcontentloaded',
                          timeout=self.timeout * 1000)
                # Wait a moment for lazy-loaded content
                page.wait_for_timeout(1500)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            logger.debug(f"Playwright fetch failed for {url}: {e}")
            return None

    def _has_useful_content(self, result):
        """Return True if the result already contains meaningful content."""
        return bool(
            (result.get('content') or '').strip() or
            (result.get('description') or '').strip()
        )

    def _extract_author(self, soup):
        """Extract author name from various common locations."""
        # Try meta tags
        for meta_attr in [
            {'property': 'article:author'},
            {'name': 'author'},
            {'property': 'og:article:author'},
        ]:
            tag = soup.find('meta', attrs=meta_attr)
            if tag and tag.get('content'):
                return tag.get('content').strip()
        
        # Try structured data
        author_tag = soup.find(attrs={'itemprop': 'author'})
        if author_tag:
            name_tag = author_tag.find(attrs={'itemprop': 'name'})
            if name_tag:
                return name_tag.get_text().strip()
            return author_tag.get_text().strip()
        
        # Try common class names
        for class_name in ['author', 'article-author', 'byline', 'author-name']:
            tag = soup.find(class_=re.compile(class_name, re.I))
            if tag:
                text = tag.get_text().strip()
                # Clean up "By Author Name" patterns
                text = re.sub(r'^by\s+', '', text, flags=re.I)
                if text and len(text) < 100:  # Sanity check
                    return text
        
        return None
    
    def _extract_time(self, soup):
        """Extract publication time from various common locations."""
        # Try meta tags
        for meta_attr in [
            {'property': 'article:published_time'},
            {'name': 'publishdate'},
            {'property': 'og:published_time'},
            {'name': 'date'},
        ]:
            tag = soup.find('meta', attrs=meta_attr)
            if tag and tag.get('content'):
                return tag.get('content').strip()
        
        # Try <time> element
        time_tag = soup.find('time')
        if time_tag:
            return time_tag.get('datetime') or time_tag.get_text().strip()
        
        # Try structured data
        time_tag = soup.find(attrs={'itemprop': 'datePublished'})
        if time_tag:
            return time_tag.get('content') or time_tag.get_text().strip()
        
        return None
    
    def _extract_description(self, soup):
        """Extract article description/summary."""
        # Try Open Graph description
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return og_desc.get('content').strip()
        
        # Try standard meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return meta_desc.get('content').strip()
        
        # Try article summary/lead paragraph
        for class_name in ['article-summary', 'article-lead', 'lead', 'summary', 'article-description']:
            tag = soup.find(class_=re.compile(class_name, re.I))
            if tag:
                text = tag.get_text().strip()
                if len(text) > 20:
                    return text
        
        return None
    
    def _extract_content(self, soup):
        """Extract main article content (all paragraphs up to 50000 chars)."""
        paragraphs = []
        
        # Try to find article body with common selectors
        for selector in [
            {'class_': re.compile(r'article-content|article-body|entry-content|post-content', re.I)},
            {'attrs': {'itemprop': 'articleBody'}},
            {'name': 'article'},
        ]:
            container = soup.find(**selector)
            if container:
                p_tags = container.find_all('p', recursive=True)
                paragraphs = [p.get_text().strip() for p in p_tags if len(p.get_text().strip()) > 30]
                if paragraphs:
                    break
        
        # Fallback: find all paragraphs on page and filter
        if not paragraphs:
            all_p = soup.find_all('p')
            paragraphs = [p.get_text().strip() for p in all_p if len(p.get_text().strip()) > 50]
        
        if paragraphs:
            full_text = '\n\n'.join(paragraphs)
            # Cap at 50000 characters to avoid storing enormous pages
            return full_text[:50000]
        
        return None


# Convenience function
def fetch_article_content(url, timeout=10):
    """
    Convenience function to fetch article content.
    Returns dict with author, published_time, description, content, and success flag.
    """
    fetcher = ArticleContentFetcher(timeout=timeout)
    return fetcher.fetch(url)


if __name__ == '__main__':
    # Test
    import sys
    
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        test_url = "https://www.haaretz.com/opinion/2026-02-27/ty-article-opinion/.premium/the-arab-communitys-democratic-threat-to-the-right/0000019c-9bb4-d5d1-a1fd-dbb6ba7e0000"
    
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 80)
    print(f"Testing: {test_url}")
    print("=" * 80)
    
    result = fetch_article_content(test_url)
    
    print(f"\n✓ Success: {result['success']}")
    print(f"✓ Author: {result['author']}")
    print(f"✓ Published: {result['published_time']}")
    print(f"✓ Description: {result['description'][:100] if result['description'] else 'None'}...")
    print(f"✓ Content (first 300 chars): {result['content'][:300] if result['content'] else 'None'}...")
