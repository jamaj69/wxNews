#!/usr/bin/env python3
"""
Sync RSS feeds from rssfeeds.conf to SQLite database.
Ensures all feeds from config file are loaded into gm_sources table.
"""
import json
import sqlite3
from urllib.parse import urlparse
import hashlib


def url_encode(text):
    """Generate a unique ID from text using MD5 hash"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def get_domain_from_url(url):
    """Extract domain from URL for source ID"""
    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '').replace('.', '-')
    return f"rss-{domain}"


def sync_rss_feeds():
    """Load RSS feeds from rssfeeds.conf and insert into SQLite database"""
    
    # Load feeds from config
    try:
        with open('rssfeeds.conf', 'r') as f:
            feeds = json.load(f)
        print(f"📡 Loaded {len(feeds)} feeds from rssfeeds.conf")
    except FileNotFoundError:
        print("❌ File rssfeeds.conf not found")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing rssfeeds.conf: {e}")
        return False
    
    # Connect to database
    try:
        conn = sqlite3.connect('predator_news.db')
        cursor = conn.cursor()
    except sqlite3.Error as e:
        print(f"❌ Database connection error: {e}")
        return False
    
    inserted = 0
    updated = 0
    skipped = 0
    errors = 0
    
    for feed in feeds:
        try:
            url = feed.get('url', '').strip()
            if not url:
                print(f"⚠️  Skipping feed with empty URL")
                skipped += 1
                continue
            
            # Generate source ID from domain
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '').replace('.', '-')
            source_id = f"rss-{domain}"
            
            # Get name from label or domain
            name = feed.get('label', '').strip() or parsed.netloc.upper()
            
            # Try to categorize
            url_lower = url.lower()
            if any(x in url_lower for x in ['business', 'finance', 'economy']):
                category = 'business'
            elif any(x in url_lower for x in ['science', 'tech', 'technology']):
                category = 'technology'
            elif any(x in url_lower for x in ['sport', 'sports']):
                category = 'sports'
            else:
                category = 'general'
            
            # Check if exists
            cursor.execute("SELECT id_source FROM gm_sources WHERE id_source = ?", (source_id,))
            exists = cursor.fetchone()
            
            if exists:
                # Update URL if different
                cursor.execute("""
                    UPDATE gm_sources 
                    SET url = ?, name = ?, category = ?
                    WHERE id_source = ?
                """, (url, name, category, source_id))
                
                if cursor.rowcount > 0:
                    updated += 1
                    print(f"  ✏️  Updated: {name}")
                else:
                    skipped += 1
            else:
                # Insert new
                cursor.execute("""
                    INSERT INTO gm_sources (id_source, name, description, url, category, language, country)
                    VALUES (?, ?, '', ?, ?, '', '')
                """, (source_id, name, url, category))
                
                inserted += 1
                print(f"  ✅ Inserted: {name}")
            
            conn.commit()
            
        except Exception as e:
            errors += 1
            print(f"  ❌ Error processing {feed.get('url', 'unknown')}: {e}")
            continue
    
    # Summary
    print(f"\n📊 Summary:")
    print(f"  ✅ Inserted: {inserted}")
    print(f"  ✏️  Updated: {updated}")
    print(f"  ⏭️  Skipped: {skipped}")
    print(f"  ❌ Errors: {errors}")
    
    # Show current count
    cursor.execute("SELECT COUNT(*) FROM gm_sources WHERE id_source LIKE 'rss-%'")
    total = cursor.fetchone()[0]
    print(f"  📡 Total RSS sources in database: {total}")
    
    conn.close()
    return True


if __name__ == '__main__':
    print("🔄 Syncing RSS feeds from rssfeeds.conf to database...\n")
    sync_rss_feeds()
