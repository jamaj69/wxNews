#!/usr/bin/env python3
"""
Fix incorrect timestamps in NZ Herald articles.
The RSS feed occasionally provides wrong dates in <pubDate> elements.
This script corrects known affected articles.
"""

import sqlite3
import sys
from datetime import datetime
from dateutil import parser
import requests
import re

def fix_specific_article():
    """Fix the known article with wrong timestamp."""
    conn = sqlite3.connect('predator_news.db')
    cursor = conn.cursor()
    
    # Fix the specific article
    url_pattern = '%X6OOBQ7Q7JECJNFE4GFFSZAFGU%'
    correct_publishedAt = 'Sat, 08 Mar 2026 23:38:00 +1300'
    correct_published_at_gmt = '2026-03-08T10:38:00+00:00'
    
    cursor.execute(
        "UPDATE gm_articles SET publishedAt=?, published_at_gmt=? WHERE url LIKE ?",
        (correct_publishedAt, correct_published_at_gmt, url_pattern)
    )
    
    print(f"Updated {cursor.rowcount} article(s)")
    
    # Verify the update
    cursor.execute(
        "SELECT id_article, title, publishedAt, published_at_gmt FROM gm_articles WHERE url LIKE ?",
        (url_pattern,)
    )
    
    row = cursor.fetchone()
    if row:
        print(f"\nVerification:")
        print(f"  ID: {row[0]}")
        print(f"  Title: {row[1][:60]}...")
        print(f"  publishedAt: {row[2]}")
        print(f"  published_at_gmt: {row[3]}")
    
    conn.commit()
    conn.close()
    
def find_suspicious_nzherald_articles():
    """Find NZ Herald articles with potentially incorrect dates."""
    conn = sqlite3.connect('predator_news.db')
    cursor = conn.cursor()
    
    # Find NZ Herald articles with dates in the far future (beyond +1 month from now)
    query = """
        SELECT a.id_article, a.title, a.publishedAt, a.published_at_gmt, a.url
        FROM gm_articles a
        JOIN gm_sources s ON a.id_source = s.id_source
        WHERE s.name LIKE '%New Zealand Herald%'
        AND datetime(a.published_at_gmt) > datetime('now', '+1 month')
        ORDER BY a.published_at_gmt
        LIMIT 20
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    
    if rows:
        print(f"\nFound {len(rows)} potentially suspicious NZ Herald articles:")
        for row in rows:
            print(f"\n  ID: {row[0]}")
            print(f"  Title: {row[1][:60]}")
            print(f"  publishedAt: {row[2]}")
            print(f"  published_at_gmt: {row[3]}")
            print(f"  URL: {row[4][:80]}")
    else:
        print("\nNo suspicious articles found")
    
    conn.close()

if __name__ == '__main__':
    print("=" * 80)
    print("Fixing NZ Herald timestamp issues")
    print("=" * 80)
    
    print("\n1. Fixing known article with wrong timestamp...")
    fix_specific_article()
    
    print("\n2. Searching for other suspicious articles...")
    find_suspicious_nzherald_articles()
    
    print("\n" + "=" * 80)
    print("Done!")
    print("=" * 80)
