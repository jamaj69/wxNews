#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite Database Setup and Population
Migrated from PostgreSQL to SQLite for simplicity

Created: 2026-02-26
"""

import json
import os
from sqlalchemy import create_engine, Table, Column, Text, MetaData
from decouple import config

print("=" * 80)
print(" SQLITE DATABASE SETUP - News Collector")
print("=" * 80)

# Get database path
db_path = config('DB_PATH', default='predator_news.db')
if not os.path.isabs(db_path):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(script_dir, db_path)

print(f"\nDatabase file: {db_path}")

# Check if database already exists
db_exists = os.path.exists(db_path)
if db_exists:
    print(f"⚠️  Database already exists ({os.path.getsize(db_path)} bytes)")
    response = input("Overwrite? [y/N]: ").strip().lower()
    if response not in ['y', 'yes']:
        print("Aborted.")
        exit(0)
    os.remove(db_path)
    print("✅ Removed old database")

# Create engine
print("\n📦 Creating SQLite databaseDatabase...")
engine = create_engine(f'sqlite:///{db_path}', echo=False)

# Create tables
metadata = MetaData()

# gm_sources table
gm_sources = Table(
    'gm_sources', metadata,
    Column('id_source', Text, primary_key=True),
    Column('name', Text),
    Column('description', Text),
    Column('url', Text),
    Column('category', Text),
    Column('language', Text),
    Column('country', Text)
)

# gm_articles table
gm_articles = Table(
    'gm_articles', metadata,
    Column('id_article', Text, primary_key=True),
    Column('id_source', Text),
    Column('author', Text),
    Column('title', Text),
    Column('description', Text),
    Column('url', Text, unique=True),
    Column('urlToImage', Text),
    Column('publishedAt', Text),
    Column('content', Text)
)

# Create all tables
metadata.create_all(engine)
print("✅ Created tables: gm_sources, gm_articles")

# Populate sources from NewsAPI JSON
json_file = 'newsapi_sources_by_category.json'

if os.path.exists(json_file):
    print(f"\n📥 Loading sources from {json_file}...")
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    filtered = data.get('filtered', {})
    conn = engine.connect()
    
    total_inserted = 0
    for category, sources in filtered.items():
        if category == 'other':
            continue
        
        print(f"\n  {category.upper()}: {len(sources)} sources")
        
        for source in sources:
            source_id = source['id'] if source['id'] else source['name'].lower().replace(' ', '-')
            
            insert_data = {
                'id_source': source_id,
                'name': source['name'],
                'description': source.get('description', ''),
                'url': source.get('url', ''),
                'category': source.get('category', 'general'),
                'language': source.get('language', 'en'),
                'country': source.get('country', 'us')
            }
            
            try:
                conn.execute(gm_sources.insert().values(**insert_data))
                total_inserted += 1
            except Exception as e:
                # Skip duplicates
                pass
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ Inserted {total_inserted} sources into database")

else:
    print(f"\n⚠️  {json_file} not found")
    print("   Run: python3 fetch_newsapi_sources.py")
    print("   Then run this script again to populate sources")

# Populate RSS sources
rss_file = 'rssfeeds_working.conf'

if os.path.exists(rss_file):
    print(f"\n📥 Loading RSS feeds from {rss_file}...")
    
    with open(rss_file, 'r') as f:
        rss_feeds = json.load(f)
    
    conn = engine.connect()
    
    for feed in rss_feeds:
        feed_url = feed.get('url', '')
        feed_label = feed.get('label', feed_url)
        
        # Create source ID from URL
        source_id = 'rss-' + feed_url.replace('https://', '').replace('http://', '').split('/')[0].replace('.', '-')[:50]
        
        insert_data = {
            'id_source': source_id,
            'name': feed_label,
            'description': f'RSS Feed: {feed_label}',
            'url': feed_url,
            'category': 'rss',
            'language': 'en',  # Default, could be enhanced
            'country': ''
        }
        
        try:
            conn.execute(gm_sources.insert().values(**insert_data))
        except:
            # Skip if duplicate
            pass
    
    conn.commit()
    conn.close()
    
    print(f"✅ Inserted RSS feeds into database")

else:
    print(f"\n⚠️  {rss_file} not found")
    print("   RSS feeds not imported")

# Summary
print("\n" + "=" * 80)
print(" DATABASE SETUP COMPLETE")
print("=" * 80)

conn = engine.connect()
source_count = conn.execute(gm_sources.select()).fetchall()
article_count = conn.execute(gm_articles.select()).fetchall()
conn.close()

print(f"\nDatabase: {db_path}")
print(f"Size: {os.path.getsize(db_path)} bytes")
print(f"Sources: {len(source_count)}")
print(f"Articles: {len(article_count)}")

print("\n✅ Ready to collect news!")
print("\nNext steps:")
print("  1. Start news collector: python3 wxAsyncNewsGather.py")
print("  2. View news GUI: python3 wxAsyncNewsReaderv5.py")
print("  3. Check database: sqlite3 predator_news.db 'SELECT COUNT(*) FROM gm_sources;'")
print("=" * 80)
