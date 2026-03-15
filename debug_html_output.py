#!/usr/bin/env python3
"""Debug: Check what HTML is being generated"""

import os
import re
import html as html_module
from html.parser import HTMLParser
from sqlalchemy import create_engine, Table, MetaData, select
from decouple import config

def dbCredentials():
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path

def dbOpen():    
    db_path = dbCredentials()
    return create_engine(f'sqlite:///{db_path}', connect_args={'timeout': 30, 'check_same_thread': False}, pool_pre_ping=True)

# Load the sanitizer from the main file
exec(open('wxAsyncNewsReaderv6.py').read().split('class NewsPanel')[0])

# Get a sample article
engine = dbOpen()
metadata = MetaData()
gm_articles = Table('gm_articles', metadata, autoload_with=engine)

with engine.connect() as conn:
    # Get recent article with description
    query = select(gm_articles).where(
        gm_articles.c.description.isnot(None)
    ).order_by(gm_articles.c.published_at_gmt.desc().nullslast()).limit(1)
    
    result = conn.execute(query).fetchone()
    
    if result:
        title = result[3]
        description = result[4]
        
        print("=" * 80)
        print(f"ARTICLE: {title[:70]}")
        print("=" * 80)
        
        print(f"\n### ORIGINAL DESCRIPTION (first 500 chars):")
        print(description[:500] if description else "None")
        
        print(f"\n### AFTER sanitize_html_content():")
        sanitized = sanitize_html_content(description) if description else ""
        print(sanitized[:500])
        
        print(f"\n### INSERTED INTO ARTICLE CARD:")
        card_html = f'''<div class="article-content">{sanitized}</div>'''
        print(card_html[:500])
        
        print(f"\n### CHECKS:")
        if '<html>' in sanitized.lower():
            print("❌ ERROR: <html> tag in sanitized output!")
        else:
            print("✅ No <html> in sanitized output")
            
        if '<body>' in sanitized.lower():
            print("❌ ERROR: <body> tag in sanitized output!")
        else:
            print("✅ No <body> in sanitized output")
            
        if '<head>' in sanitized.lower():
            print("❌ ERROR: <head> tag in sanitized output!")
        else:
            print("✅ No <head> in sanitized output")
