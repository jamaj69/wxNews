#!/usr/bin/env python3
"""Test sanitization with actual database content"""

import os
import html as html_module
import re
from sqlalchemy import create_engine, Table, MetaData, select
from decouple import config

def dbCredentials():
    """Return SQLite database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path

def dbOpen():    
    """Open database connection with SQLAlchemy"""
    db_path = dbCredentials()
    eng = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False},
        pool_pre_ping=True
    )
    return eng

def sanitize_html_content(html_content):
    """Sanitize HTML content"""
    if not html_content:
        return ""
    
    print(f"BEFORE unescape (first 200 chars): {html_content[:200]}")
    
    # Unescape HTML entities (in case content is stored escaped in DB)
    html_content = html_module.unescape(html_content)
    
    print(f"AFTER unescape (first 200 chars): {html_content[:200]}")
    
    # Check if content has HTML tags
    if '<' not in html_content or '>' not in html_content:
        return f"<p>{html_content}</p>"
    
    # Remove script and style tags completely
    html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove <html>, <head>, <body> wrapper tags (but keep their content)
    html_content = re.sub(r'<html[^>]*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'</html>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<head[^>]*>.*?</head>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<body[^>]*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'</body>', '', html_content, flags=re.IGNORECASE)
    
    print(f"AFTER removing html/body tags (first 200 chars): {html_content[:200]}")
    
    # Remove class attributes
    html_content = re.sub(r'\sclass=["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sclass=[^\s>]+', '', html_content, flags=re.IGNORECASE)
    
    # Remove style attributes
    html_content = re.sub(r'\sstyle=["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sstyle=[^\s>]+', '', html_content, flags=re.IGNORECASE)
    
    # Remove align attributes
    html_content = re.sub(r'\salign=["\']?[^"\'\s>]*["\']?', '', html_content, flags=re.IGNORECASE)
    
    # Fix img tags
    html_content = re.sub(
        r'<img\s+([^>]*)>',
        r'<img \1 style="max-width: 100%; height: auto; display: block; margin: 10px 0;">',
        html_content,
        flags=re.IGNORECASE
    )
    
    # Clean up whitespace
    html_content = re.sub(r'\s+', ' ', html_content).strip()
    
    return html_content

# Connect to database
engine = dbOpen()
metadata = MetaData()
gm_articles = Table('gm_articles', metadata, autoload_with=engine)

# Get articles with HTML in their descriptions
with engine.connect() as conn:
    query = select(gm_articles).where(
        gm_articles.c.description.isnot(None)
    ).limit(50)
    
    results = conn.execute(query).fetchall()
    
    # Filter for articles with HTML content
    html_articles = []
    for article in results:
        description = article[4] if len(article) > 4 else None
        if description and ('<html' in description.lower() or '<body' in description.lower() or '<img' in description.lower() or '<p>' in description.lower()):
            html_articles.append(article)
    
    print("=" * 80)
    print(f"Found {len(html_articles)} articles with HTML in descriptions (out of {len(results)} checked)")
    print("=" * 80)
    
    for i, article in enumerate(html_articles[:3], 1):  # Test first 3 HTML articles
        # Access by index
        title = article[3] if len(article) > 3 else "No title"
        description = article[4] if len(article) > 4 else None
        
        print(f"\n{'=' * 80}")
        print(f"ARTICLE #{i}: {title[:60] if title else 'No title'}...")
        print(f"{'=' * 80}")
        
        if description:
            print(f"\nOriginal description length: {len(description)}")
            print(f"Original (first 500 chars):\n{description[:500]}")
            
            print(f"\n--- SANITIZING ---")
            sanitized = sanitize_html_content(description)
            
            print(f"\nSanitized length: {len(sanitized)}")
            print(f"Sanitized (first 500 chars):\n{sanitized[:500]}")
            
            # Check for problems
            if '<html>' in sanitized.lower() or '</html>' in sanitized.lower():
                print("\n❌ ERROR: <html> tag still present!")
                print(f"Full sanitized output:\n{sanitized}")
            if '<body>' in sanitized.lower() or '</body>' in sanitized.lower():
                print("\n❌ ERROR: <body> tag still present!")
            if '<head>' in sanitized.lower() or '</head>' in sanitized.lower():
                print("\n❌ ERROR: <head> tag still present!")
            
            if '<img' in sanitized.lower():
                print("\n✅ GOOD: <img> tag preserved")
            
            if 'class=' in sanitized.lower():
                print("\n⚠️ WARNING: class attribute still present!")
                
            if '<p>' in sanitized.lower():
                print("\n✅ GOOD: <p> tag preserved")
