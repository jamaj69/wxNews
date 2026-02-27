#!/usr/bin/env python
"""Quick test of reader filtering logic"""

from sqlalchemy import create_engine, MetaData, Table, select, func
import time

MIN_ARTICLES = 10
MAX_SOURCES = 50

print("Connecting to database...")
eng = create_engine('sqlite:///predator_news.db')
meta = MetaData()
gm_sources = Table('gm_sources', meta, autoload_with=eng)
gm_articles = Table('gm_articles', meta, autoload_with=eng)

print("Starting optimized filtering...")
start = time.time()

con = eng.connect()
stm = select(gm_sources)
rs = con.execute(stm)

# First pass: count articles per source (lightweight)
source_list = []
sources_checked = 0
for source in rs.fetchall():
    sources_checked += 1
    source_id = source[0]
    # Use COUNT to get article count efficiently
    stm1 = select(func.count()).select_from(gm_articles).where(gm_articles.c.id_source == source_id)
    article_count = con.execute(stm1).scalar()
    
    # Only keep sources with minimum article count AND non-empty names
    source_name = source[1] if source[1] else ""
    if article_count >= MIN_ARTICLES and source_name.strip():
        source_list.append({
            'source_id': source_id,
            'source_name': source_name.strip(),
            'article_count': article_count
        })

count_time = time.time()
print(f"Phase 1 (counting): Checked {sources_checked} sources in {count_time-start:.2f}s")
print(f"  Found {len(source_list)} sources with >= {MIN_ARTICLES} articles")

# Sort by article count (most articles first)
source_list.sort(key=lambda x: x['article_count'], reverse=True)

# Limit to top N sources
source_list = source_list[:MAX_SOURCES]

print(f"\nTop {len(source_list)} sources selected:")
for i, item in enumerate(source_list[:10], 1):
    print(f"  {i}. {item['source_name']}: {item['article_count']} articles")

# Second pass: load full articles ONLY for filtered sources
print(f"\nPhase 2: Loading articles for {len(source_list)} sources...")
total_articles = 0
for item in source_list:
    source_id = item['source_id']
    stm2 = select(gm_articles).where(gm_articles.c.id_source == source_id)
    articles_qry = con.execute(stm2)
    articles = articles_qry.fetchall()
    total_articles += len(articles)

load_time = time.time()
print(f"Phase 2 (loading): Loaded {total_articles} articles in {load_time-count_time:.2f}s")
print(f"\nTotal time: {load_time-start:.2f}s")

con.close()
print("\n✅ Test completed successfully")
