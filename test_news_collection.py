#!/usr/bin/env python3
"""
Simple test script to verify news collection and database insertion works.
"""
import asyncio
import aiohttp
import json
from sqlalchemy import create_engine, MetaData, Table, select
from sqlalchemy.dialects.sqlite import insert
from decouple import config
import hashlib

def url_encode(text):
    """Create unique ID from text"""
    return hashlib.md5(text.encode()).hexdigest()

def get_db():
    """Get database connection"""
    db_path = config('DATABASE_PATH', default='predator_news.db')
    eng = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False},
        pool_pre_ping=True
    )
    meta = MetaData()
    gm_sources = Table('gm_sources', meta, autoload_with=eng)
    gm_articles = Table('gm_articles', meta, autoload_with=eng)
    return eng, gm_sources, gm_articles

async def fetch_and_store_news():
    """Fetch news from NewsAPI and store in database"""
    API_KEY = config('NEWS_API_KEY_1')
    url = f'https://newsapi.org/v2/top-headlines?language=en&pageSize=10&apiKey={API_KEY}'
    
    print(f'Fetching from NewsAPI...')
    
    eng, gm_sources, gm_articles = get_db()
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                print(f'Error: HTTP {response.status}')
                return
            
            text = await response.text()
            data = json.loads(text)
            
            if data.get('status') != 'ok':
                print(f'API Error: {data.get("message")}')
                return
            
            articles = data.get('articles', [])
            print(f'Received {len(articles)} articles')
            
            inserted_count = 0
            skipped_count = 0
            
            with eng.connect() as conn:
                for article in articles:
                    try:
                        # Extract article data
                        source = article.get('source', {})
                        source_id = source.get('id') or source.get('name') or 'unknown'
                        source_name = source.get('name', 'Unknown')
                        
                        article_title = article.get('title', '')
                        article_url = article.get('url', '')
                        article_published = article.get('publishedAt', '')
                        
                        # Create unique article ID
                        article_key = url_encode(article_title + article_url + article_published)
                        
                        # Check if source exists, if not create it
                        stmt = select(gm_sources).where(gm_sources.c.id_source == source_id)
                        result = conn.execute(stmt)
                        if not result.fetchone():
                            new_source = {
                                'id_source': source_id,
                                'name': source_name,
                                'url': '',
                                'description': '',
                                'category': '',
                                'country': '',
                                'language': 'en'
                            }
                            ins = insert(gm_sources).values(**new_source)
                            conn.execute(ins)
                            print(f'  Added new source: {source_name}')
                        
                        # Insert article
                        new_article = {
                            'id_article': article_key,
                            'id_source': source_id,
                            'author': article.get('author', ''),
                            'title': article_title[:200],  # Truncate if needed
                            'description': article.get('description', ''),
                            'url': article_url,
                            'urlToImage': article.get('urlToImage', ''),
                            'publishedAt': article_published,
                            'content': article.get('content', '')
                        }
                        
                        ins = insert(gm_articles).values(**new_article)
                        ins_do_nothing = ins.on_conflict_do_nothing(index_elements=['id_article'])
                        result = conn.execute(ins_do_nothing)
                        
                        if result.rowcount > 0:
                            print(f'  ✅ [{source_name}] {article_title[:60]}...')
                            inserted_count += 1
                        else:
                            print(f'  ⏭️  [{source_name}] Already exists: {article_title[:40]}...')
                            skipped_count += 1
                            
                    except Exception as e:
                        print(f'  ❌ Error processing article: {e}')
                        continue
                
                conn.commit()
            
            print(f'\n✅ Summary: {inserted_count} inserted, {skipped_count} skipped')

if __name__ == '__main__':
    print('=== News Collection Test ===\n')
    asyncio.run(fetch_and_store_news())
    
    # Check database
    print('\n=== Database Check ===')
    eng, _, gm_articles = get_db()
    with eng.connect() as conn:
        stmt = select(gm_articles)
        result = conn.execute(stmt)
        count = len(result.fetchall())
        print(f'Total articles in database: {count}')
