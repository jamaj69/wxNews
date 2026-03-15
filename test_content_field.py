#!/usr/bin/env python3
"""Check if content field has HTML"""

import os
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
    eng = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False},
        pool_pre_ping=True
    )
    return eng

# Connect to database
engine = dbOpen()
metadata = MetaData()
gm_articles = Table('gm_articles', metadata, autoload_with=engine)

# Get articles with content
with engine.connect() as conn:
    query = select(gm_articles).where(
        gm_articles.c.content.isnot(None)
    ).limit(50)
    
    results = conn.execute(query).fetchall()
    
    # Check content field
    html_in_content = []
    for article in results:
        content = article[8] if len(article) > 8 else None  # content is column 8
        if content and ('<html' in content.lower() or '<body' in content.lower()):
            html_in_content.append(article)
    
    print("=" * 80)
    print(f"Checked {len(results)} articles")
    print(f"Found {len(html_in_content)} articles with HTML in CONTENT field")
    print("=" * 80)
    
    for i, article in enumerate(html_in_content[:3], 1):
        title = article[3] if len(article) > 3 else "No title"
        content = article[8] if len(article) > 8 else None
        
        print(f"\n{'=' * 80}")
        print(f"ARTICLE #{i}: {title[:60]}...")
        print(f"{'=' * 80}")
        
        if content:
            print(f"\nContent length: {len(content)}")
            print(f"Content (first 500 chars):\n{content[:500]}")
            
            if '<html>' in content.lower():
                print("\n⚠️ Has <html> tag in CONTENT field!")
            if '<body>' in content.lower():
                print("\n⚠️ Has <body> tag in CONTENT field!")
