#!/usr/bin/env python3
"""
Test script to fetch and parse article content from a URL.
"""

import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

def fetch_article_content(url, timeout=10):
    """
    Fetch article content from a URL and extract:
    - Author
    - Publication time
    - First few paragraphs of text
    - Any available description/summary
    
    Returns dict with extracted data or None if failed.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        print(f"🌐 Fetching: {url}")
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract data
        result = {
            'author': None,
            'published_time': None,
            'description': None,
            'content': None,
            'first_paragraph': None
        }
        
        # Try to find author - common patterns
        author_selectors = [
            {'name': 'meta', 'property': 'article:author'},
            {'name': 'meta', 'name': 'author'},
            {'class': 'author'},
            {'class': 'article-author'},
            {'itemprop': 'author'},
        ]
        
        for selector in author_selectors:
            author_tag = soup.find(**selector)
            if author_tag:
                result['author'] = author_tag.get('content') or author_tag.get_text().strip()
                if result['author']:
                    print(f"✓ Author: {result['author']}")
                    break
        
        # Try to find publication time
        time_selectors = [
            {'name': 'meta', 'property': 'article:published_time'},
            {'name': 'meta', 'name': 'publishdate'},
            {'name': 'time'},
            {'class': 'publish-date'},
            {'class': 'article-date'},
        ]
        
        for selector in time_selectors:
            time_tag = soup.find(**selector)
            if time_tag:
                result['published_time'] = time_tag.get('content') or time_tag.get('datetime') or time_tag.get_text().strip()
                if result['published_time']:
                    print(f"✓ Published: {result['published_time']}")
                    break
        
        # Try to find description/summary
        desc_selectors = [
            {'name': 'meta', 'property': 'og:description'},
            {'name': 'meta', 'name': 'description'},
            {'class': 'article-summary'},
            {'class': 'article-description'},
        ]
        
        for selector in desc_selectors:
            desc_tag = soup.find(**selector)
            if desc_tag:
                result['description'] = desc_tag.get('content') or desc_tag.get_text().strip()
                if result['description'] and len(result['description']) > 20:
                    print(f"✓ Description: {result['description'][:100]}...")
                    break
        
        # Try to find article content
        content_selectors = [
            {'class': 'article-content'},
            {'class': 'article-body'},
            {'class': 'entry-content'},
            {'itemprop': 'articleBody'},
            {'name': 'article'},
        ]
        
        paragraphs = []
        for selector in content_selectors:
            content_tag = soup.find(**selector)
            if content_tag:
                # Extract all paragraphs
                p_tags = content_tag.find_all('p')
                paragraphs = [p.get_text().strip() for p in p_tags if p.get_text().strip()]
                if paragraphs:
                    print(f"✓ Found {len(paragraphs)} paragraphs")
                    break
        
        # If no structured content found, try to find all paragraphs in the page
        if not paragraphs:
            all_p = soup.find_all('p')
            # Filter out very short paragraphs (likely navigation, etc.)
            paragraphs = [p.get_text().strip() for p in all_p if len(p.get_text().strip()) > 50]
            print(f"✓ Found {len(paragraphs)} paragraphs (fallback)")
        
        if paragraphs:
            result['first_paragraph'] = paragraphs[0]
            result['content'] = '\n\n'.join(paragraphs[:5])  # First 5 paragraphs
            print(f"✓ First paragraph: {result['first_paragraph'][:100]}...")
        
        return result
        
    except requests.RequestException as e:
        print(f"❌ Request error: {e}")
        return None
    except Exception as e:
        print(f"❌ Parse error: {e}")
        return None


# Test with the Haaretz article
if __name__ == '__main__':
    test_url = "https://www.haaretz.com/opinion/2026-02-27/ty-article-opinion/.premium/the-arab-communitys-democratic-threat-to-the-right/0000019c-9bb4-d5d1-a1fd-dbb6ba7e0000"
    
    print("=" * 80)
    print("Testing article content extraction")
    print("=" * 80)
    
    result = fetch_article_content(test_url)
    
    if result:
        print("\n" + "=" * 80)
        print("RESULTS:")
        print("=" * 80)
        print(f"\nAuthor: {result['author']}")
        print(f"Published: {result['published_time']}")
        print(f"\nDescription:\n{result['description']}")
        print(f"\nFirst Paragraph:\n{result['first_paragraph']}")
        print(f"\nFull Content (first 500 chars):\n{result['content'][:500] if result['content'] else 'None'}")
    else:
        print("\n❌ Failed to extract article content")
