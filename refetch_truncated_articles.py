#!/usr/bin/env python3
"""
Re-fetch truncated articles from their URLs and update with complete content.
Uses the same logic as wxAsyncNewsGather enrichment.
"""

import sqlite3
import sys
import os
import html
import re
from html.parser import HTMLParser
from decouple import config

# Import article fetcher
from article_fetcher import fetch_article_content


# ============================================================================
# HTML Sanitization (same as wxAsyncNewsGather)
# ============================================================================

class HTMLContentSanitizer(HTMLParser):
    """Parse HTML and extract only body content, removing unwanted tags and attributes"""
    
    SKIP_TAGS = {'script', 'style', 'head', 'meta', 'link', 'noscript'}
    WRAPPER_TAGS = {'html', 'body', 'div', 'span', 'section', 'article'}
    REMOVE_ATTRS = {'class', 'id', 'style', 'onclick', 'onload', 'onerror', 
                    'align', 'width', 'height'}
    KEEP_TAGS = {'p', 'br', 'img', 'a', 'b', 'i', 'strong', 'em', 'u'}
    KEEP_ATTRS = {
        'img': {'src', 'alt'},
        'a': {'href'},
    }
    
    def __init__(self):
        super().__init__()
        self.content = []
        self.skip_level = 0
    
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_level += 1
            return
        
        if self.skip_level > 0:
            return
        
        if tag in self.WRAPPER_TAGS:
            return
        
        if tag not in self.KEEP_TAGS:
            return
        
        allowed_attrs = self.KEEP_ATTRS.get(tag, set())
        filtered_attrs = []
        
        for attr, value in attrs:
            if attr not in self.REMOVE_ATTRS and (not allowed_attrs or attr in allowed_attrs):
                if attr == 'alt' and value and len(value) > 100:
                    continue
                filtered_attrs.append((attr, value))
        
        if filtered_attrs:
            attrs_str = ' '.join(f'{attr}="{value}"' for attr, value in filtered_attrs)
            self.content.append(f'<{tag} {attrs_str}>')
        else:
            self.content.append(f'<{tag}>')
    
    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self.skip_level = max(0, self.skip_level - 1)
            return
        
        if self.skip_level > 0:
            return
        
        if tag in self.WRAPPER_TAGS:
            return
        
        if tag not in self.KEEP_TAGS:
            return
        
        self.content.append(f'</{tag}>')
    
    def handle_data(self, data):
        if self.skip_level == 0:
            self.content.append(data)
    
    def handle_startendtag(self, tag, attrs):
        if tag in self.SKIP_TAGS or self.skip_level > 0:
            return
        
        if tag in self.WRAPPER_TAGS:
            return
        
        if tag not in self.KEEP_TAGS:
            return
        
        allowed_attrs = self.KEEP_ATTRS.get(tag, set())
        filtered_attrs = []
        
        for attr, value in attrs:
            if attr not in self.REMOVE_ATTRS and (not allowed_attrs or attr in allowed_attrs):
                if attr == 'alt' and value and len(value) > 100:
                    continue
                filtered_attrs.append((attr, value))
        
        if filtered_attrs:
            attrs_str = ' '.join(f'{attr}="{value}"' for attr, value in filtered_attrs)
            self.content.append(f'<{tag} {attrs_str} />')
        else:
            self.content.append(f'<{tag} />')
    
    def get_content(self):
        return ''.join(self.content)


def sanitize_html_content(html_content):
    """Sanitize HTML content"""
    if not html_content:
        return ""
    
    html_content = html.unescape(html_content)
    
    if '<' not in html_content or '>' not in html_content:
        return f"<p>{html_content}</p>"
    
    parser = HTMLContentSanitizer()
    try:
        parser.feed(html_content)
        parser.close()
        result = parser.get_content()
        
        if not result or len(result.strip()) < 3:
            plain = re.sub(r'<[^>]*>', '', html_content)
            plain = re.sub(r'\s+', ' ', plain).strip()
            return f"<p>{plain}</p>" if plain else ""
        
        return result.strip()
    except Exception as e:
        plain = re.sub(r'<[^>]*>', '', html_content)
        plain = re.sub(r'\s+', ' ', plain).strip()
        return f"<p>{plain}</p>" if plain else ""


def extract_first_image_url(html_content):
    """Extract the first image URL from HTML content"""
    if not html_content:
        return None
    
    try:
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        if img_match:
            url = img_match.group(1)
            if url.startswith(('http://', 'https://')):
                return url
    except Exception:
        pass
    
    return None


def dbCredentials():
    """Return SQLite database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path


def find_truncated_articles(conn, limit=None):
    """Find articles that appear to be truncated"""
    cursor = conn.cursor()
    
    query = """
    SELECT 
        id_article, 
        title,
        description,
        url,
        urlToImage,
        content,
        id_source
    FROM gm_articles 
    WHERE 
        LENGTH(description) = 500
        OR (description LIKE '%</%' AND description NOT LIKE '%</p>%' 
            AND description NOT LIKE '%</a>%' AND description NOT LIKE '%</b>%')
    ORDER BY published_at_gmt DESC
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query)
    return cursor.fetchall()


def refetch_article(article, timeout=10):
    """Re-fetch article content from URL"""
    article_id, title, description, url, url_to_image, content, source_id = article
    
    if not url or not url.startswith(('http://', 'https://')):
        return None
    
    print(f"  🔍 Fetching: {title[:60]}...")
    
    try:
        result = fetch_article_content(url, timeout)
        
        if not result or not result.get('success'):
            print(f"     ❌ Fetch failed")
            return None
        
        updates = {}
        
        # Update description if we got better content
        if result.get('description'):
            clean_desc = sanitize_html_content(result['description'])
            if clean_desc and len(clean_desc) > len(description or ''):
                updates['description'] = clean_desc
                print(f"     ✅ Updated description ({len(clean_desc)} chars)")
        
        # Update content
        if result.get('content'):
            clean_content = sanitize_html_content(result['content'])
            if clean_content:
                updates['content'] = clean_content
                print(f"     ✅ Updated content ({len(clean_content)} chars)")
        
        # Extract image from description if urlToImage is missing
        if not url_to_image:
            if result.get('description'):
                img_url = extract_first_image_url(result['description'])
                if img_url:
                    updates['urlToImage'] = img_url
                    print(f"     🖼️  Extracted image URL")
        
        if updates:
            updates['id_article'] = article_id
            return updates
        else:
            print(f"     ⚠️  No improvements found")
            return None
            
    except Exception as e:
        print(f"     ❌ Error: {e}")
        return None


def update_article(conn, updates):
    """Update article in database"""
    cursor = conn.cursor()
    
    fields = []
    values = []
    
    for key, value in updates.items():
        if key != 'id_article':
            fields.append(f"{key} = ?")
            values.append(value)
    
    values.append(updates['id_article'])
    
    query = f"UPDATE gm_articles SET {', '.join(fields)} WHERE id_article = ?"
    cursor.execute(query, values)


def main():
    db_path = dbCredentials()
    print(f"📊 Connecting to database: {db_path}\n")
    
    conn = sqlite3.connect(db_path)
    
    try:
        # Find truncated articles
        print("🔍 Finding truncated articles...")
        truncated = find_truncated_articles(conn)
        
        if not truncated:
            print("✅ No truncated articles found!")
            return 0
        
        print(f"Found {len(truncated)} truncated articles\n")
        
        # Ask for confirmation
        response = input(f"Re-fetch and update these {len(truncated)} articles? [y/N]: ").strip().lower()
        if response != 'y':
            print("❌ Cancelled")
            return 1
        
        print("\n🚀 Starting re-fetch process...\n")
        
        updated_count = 0
        failed_count = 0
        
        for i, article in enumerate(truncated, 1):
            print(f"[{i}/{len(truncated)}]")
            
            updates = refetch_article(article)
            
            if updates:
                update_article(conn, updates)
                conn.commit()
                updated_count += 1
            else:
                failed_count += 1
            
            print()
        
        print("=" * 70)
        print(f"✅ Updated: {updated_count}")
        print(f"❌ Failed/No changes: {failed_count}")
        print(f"📊 Total processed: {len(truncated)}")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
