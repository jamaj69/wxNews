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
        """
        result = {
            'author': None,
            'published_time': None,
            'description': None,
            'content': None,
            'success': False,
            'error_code': None
        }
        
        try:
            logger.debug(f"Fetching content from: {url}")
            headers = self._get_headers_for_url(url)
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            
            # Try lxml parser first (faster and more robust for most sites)
            # Fall back to html.parser if lxml fails
            soup = None
            for parser in ['lxml', 'html.parser']:
                try:
                    soup = BeautifulSoup(response.text, parser)
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
            logger.debug(f"Successfully extracted content from {url}")
            
        except requests.HTTPError as e:
            # Capture HTTP error code (403, 404, etc.)
            if e.response is not None:
                result['error_code'] = e.response.status_code
            logger.error(f"Request error for {url}: {e}")
        except requests.Timeout as e:
            # Connection or read timeout
            result['error_code'] = 'TIMEOUT'
            logger.error(f"Request error for {url}: {e}")
        except requests.RequestException as e:
            logger.error(f"Request error for {url}: {e}")
        except Exception as e:
            logger.error(f"Parse error for {url}: {e}")
        
        return result
    
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
        """Extract main article content (first few paragraphs)."""
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
        
        # Return first 3-5 paragraphs
        if paragraphs:
            return '\n\n'.join(paragraphs[:5])
        
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
