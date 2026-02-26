#!/usr/bin/env python3
"""
MediaStack API News Collector
Collects news from MediaStack API (https://mediastack.com/)
Free tier: 500 requests/month, 7,500+ sources
"""

import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import List, Dict, Optional
from decouple import config
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.dialects.sqlite import insert

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MediaStackCollector:
    """Collector for MediaStack API news"""
    
    def __init__(self, db_path: str = 'predator_news.db'):
        """Initialize MediaStack collector"""
        self.api_key = config('MEDIASTACK_API_KEY')
        self.base_url = config('MEDIASTACK_BASE_URL', default='https://api.mediastack.com/v1/news')
        self.db_path = db_path
        
        # Database setup
        self.engine = create_engine(
            f'sqlite:///{self.db_path}',
            connect_args={'timeout': 30, 'check_same_thread': False}
        )
        self.metadata = MetaData()
        self.sources_table = Table('gm_sources', self.metadata, autoload_with=self.engine)
        self.articles_table = Table('gm_articles', self.metadata, autoload_with=self.engine)
        
        logger.info(f"✅ MediaStackCollector initialized with database: {db_path}")
    
    async def fetch_news(
        self, 
        session: aiohttp.ClientSession,
        languages: str = 'en',
        countries: Optional[str] = None,
        categories: Optional[str] = None,
        sources: Optional[str] = None,
        keywords: Optional[str] = None,
        date: Optional[str] = None,
        sort: str = 'published_desc',
        limit: int = 25,
        offset: int = 0
    ) -> Dict:
        """
        Fetch news from MediaStack API
        
        Args:
            session: aiohttp session
            languages: Comma-separated language codes (en,es,pt,it,ar,de,fr,he,nl,no,ru,se,zh)
            countries: Comma-separated 2-letter country codes (us,gb,br,es,it,au,ca,de,fr)
            categories: Comma-separated categories (general,business,entertainment,health,science,sports,technology)
            sources: Comma-separated source IDs (cnn,bbc,bloomberg). Use -source to exclude
            keywords: Search keywords. Use -keyword to exclude. Example: "AI technology -crypto"
            date: Date (YYYY-MM-DD) or date range (YYYY-MM-DD,YYYY-MM-DD)
            sort: Sorting order (published_desc, published_asc, popularity)
            limit: Number of articles to fetch (max 100, default 25)
            offset: Pagination offset
        
        Returns:
            Dict with pagination and data
        """
        params = {
            'access_key': self.api_key,
            'languages': languages,
            'sort': sort,
            'limit': min(limit, 100),  # MediaStack max is 100
            'offset': offset
        }
        
        if countries:
            params['countries'] = countries
        
        if categories:
            params['categories'] = categories
        
        if sources:
            params['sources'] = sources
        
        if keywords:
            params['keywords'] = keywords
        
        if date:
            params['date'] = date
        
        try:
            async with session.get(self.base_url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Check for API errors
                    if 'error' in data:
                        error_info = data['error']
                        logger.error(f"❌ MediaStack API Error: {error_info.get('code')} - {error_info.get('message')}")
                        return {'pagination': {}, 'data': []}
                    
                    articles_count = len(data.get('data', []))
                    total = data.get('pagination', {}).get('total', 0)
                    logger.info(f"📥 MediaStack: Received {articles_count}/{total} articles (lang: {languages})")
                    return data
                elif response.status == 429:
                    logger.error(f"❌ MediaStack: Rate limit exceeded (429)")
                    return {'pagination': {}, 'data': []}
                elif response.status == 401:
                    logger.error(f"❌ MediaStack: Invalid API key (401)")
                    return {'pagination': {}, 'data': []}
                else:
                    error_text = await response.text()
                    logger.error(f"❌ MediaStack: HTTP {response.status} - {error_text}")
                    return {'pagination': {}, 'data': []}
        
        except asyncio.TimeoutError:
            logger.error(f"⏱️  MediaStack: Timeout")
            return {'pagination': {}, 'data': []}
        except Exception as e:
            logger.error(f"❌ MediaStack: Error - {str(e)}")
            return {'pagination': {}, 'data': []}
    
    def process_article(self, article: Dict, language: str) -> Optional[Dict]:
        """
        Process a MediaStack article into our database format
        
        Args:
            article: MediaStack article data
            language: Language code
        
        Returns:
            Processed article dict or None if invalid
        """
        try:
            # Extract data
            title = article.get('title', '').strip()
            url = article.get('url', '').strip()
            description = article.get('description', '').strip()
            author = article.get('author', '').strip()
            source_name = article.get('source', 'unknown').strip()
            category = article.get('category', 'general').strip()
            published_at = article.get('published_at', '')
            
            # Validate required fields
            if not title or not url:
                logger.debug(f"⚠️  Skipping article: missing title or URL")
                return None
            
            # Parse date
            try:
                if published_at:
                    pub_date = datetime.fromisoformat(published_at.replace('+00:00', ''))
                else:
                    pub_date = datetime.utcnow()
            except ValueError:
                pub_date = datetime.utcnow()
            
            # Create source ID (mediastack-source_name)
            source_id = f"mediastack-{source_name.lower().replace(' ', '-')}"
            
            # Create article ID (hash of URL)
            import hashlib
            article_id = hashlib.md5(url.encode()).hexdigest()[:16]
            
            return {
                'id_article': f"ms-{article_id}",
                'id_source': source_id,
                'source_name': source_name,
                'title': title[:500] if title else '',  # Limit title length
                'description': description[:1000] if description else '',  # Limit description
                'url': url[:500] if url else '',
                'author': author[:200] if author else '',
                'language': language,
                'category': category,
                'published_at': pub_date
            }
        
        except Exception as e:
            logger.error(f"❌ Error processing article: {str(e)}")
            return None
    
    def ensure_source_exists(self, source_id: str, source_name: str, language: str, category: str):
        """Ensure source exists in database"""
        try:
            with self.engine.connect() as conn:
                # Check if source exists
                from sqlalchemy import select
                stmt = select(self.sources_table.c.id_source).where(
                    self.sources_table.c.id_source == source_id
                )
                result = conn.execute(stmt).fetchone()
                
                if not result:
                    # Insert new source
                    ins = insert(self.sources_table).values(
                        id_source=source_id,
                        name=source_name,
                        language=language,
                        category=category,
                        url='',  # MediaStack doesn't provide source URLs
                        country=''
                    )
                    ins = ins.on_conflict_do_nothing(index_elements=['id_source'])
                    conn.execute(ins)
                    conn.commit()
                    logger.debug(f"✅ Created source: {source_id}")
        
        except Exception as e:
            logger.error(f"❌ Error ensuring source exists: {str(e)}")
    
    async def collect_and_store(
        self,
        languages: List[str] = ['en'],
        countries: Optional[str] = None,
        categories: Optional[str] = None,
        sources: Optional[str] = None,
        keywords: Optional[str] = None,
        date: Optional[str] = None,
        sort: str = 'published_desc',
        limit: int = 25
    ) -> Dict[str, int]:
        """
        Collect news from MediaStack and store in database
        
        Args:
            languages: List of language codes (en, es, pt, it, ar, de, fr, etc.)
            countries: Comma-separated country codes (us,gb,br,es,it,au,ca,de,fr)
            categories: Comma-separated categories (general,business,entertainment,health,science,sports,technology)
            sources: Comma-separated source IDs. Use -source to exclude
            keywords: Search keywords. Use -keyword to exclude
            date: Date (YYYY-MM-DD) or range (YYYY-MM-DD,YYYY-MM-DD)
            sort: Sorting (published_desc, published_asc, popularity)
            limit: Articles per language (max 100)
        
        Returns:
            Dict with statistics
        """
        stats = {
            'total_fetched': 0,
            'inserted': 0,
            'skipped': 0,
            'errors': 0
        }
        
        async with aiohttp.ClientSession() as session:
            for language in languages:
                logger.info(f"🌍 Collecting MediaStack news for language: {language}")
                
                # Fetch news
                response = await self.fetch_news(
                    session=session,
                    languages=language,
                    countries=countries,
                    categories=categories,
                    sources=sources,
                    keywords=keywords,
                    date=date,
                    sort=sort,
                    limit=limit
                )
                
                articles = response.get('data', [])
                stats['total_fetched'] += len(articles)
                
                # Process and store articles
                with self.engine.connect() as conn:
                    for article_data in articles:
                        processed = self.process_article(article_data, language)
                        
                        if not processed:
                            stats['errors'] += 1
                            continue
                        
                        try:
                            # Ensure source exists
                            self.ensure_source_exists(
                                processed['id_source'],
                                processed['source_name'],
                                language,
                                processed['category']
                            )
                            
                            # Insert article (note: table uses publishedAt, not published_at)
                            ins = insert(self.articles_table).values(
                                id_article=processed['id_article'],
                                id_source=processed['id_source'],
                                title=processed['title'],
                                description=processed['description'],
                                url=processed['url'],
                                author=processed['author'],
                                publishedAt=processed['published_at'].isoformat() if processed['published_at'] else None
                            )
                            ins = ins.on_conflict_do_nothing(index_elements=['id_article'])
                            
                            result = conn.execute(ins)
                            conn.commit()
                            
                            if result.rowcount > 0:
                                stats['inserted'] += 1
                                logger.debug(f"  ✅ Inserted: {processed['title'][:50]}...")
                            else:
                                stats['skipped'] += 1
                        
                        except Exception as e:
                            stats['errors'] += 1
                            logger.error(f"❌ Error storing article: {str(e)}")
        
        return stats


async def test_mediastack():
    """Test MediaStack collector"""
    logger.info("="*80)
    logger.info("🧪 Testing MediaStack API Collector")
    logger.info("="*80)
    
    collector = MediaStackCollector()
    
    # Test 1: Technology news in English
    logger.info("\n📰 Test 1: Technology news in English...")
    stats1 = await collector.collect_and_store(
        languages=['en'],
        categories='technology',
        limit=10
    )
    
    # Test 2: Business news in multiple languages
    logger.info("\n📰 Test 2: Business news in PT and ES...")
    stats2 = await collector.collect_and_store(
        languages=['pt', 'es'],
        categories='business',
        limit=5
    )
    
    # Test 3: Search with keywords
    logger.info("\n📰 Test 3: AI news excluding crypto...")
    stats3 = await collector.collect_and_store(
        languages=['en'],
        keywords='AI technology -crypto',
        limit=5
    )
    
    # Combined statistics
    total_stats = {
        'total_fetched': stats1['total_fetched'] + stats2['total_fetched'] + stats3['total_fetched'],
        'inserted': stats1['inserted'] + stats2['inserted'] + stats3['inserted'],
        'skipped': stats1['skipped'] + stats2['skipped'] + stats3['skipped'],
        'errors': stats1['errors'] + stats2['errors'] + stats3['errors']
    }
    
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 MEDIASTACK TEST RESULTS (COMBINED)")
    logger.info(f"  Total fetched: {total_stats['total_fetched']}")
    logger.info(f"  ✅ Inserted: {total_stats['inserted']}")
    logger.info(f"  ⏭️  Skipped: {total_stats['skipped']}")
    logger.info(f"  ❌ Errors: {total_stats['errors']}")
    logger.info(f"{'='*80}")
    logger.info(f"\n💡 MediaStack Features Demonstrated:")
    logger.info(f"  ✅ Category filtering (technology, business)")
    logger.info(f"  ✅ Multi-language support (en, pt, es)")
    logger.info(f"  ✅ Keyword search with exclusion")
    logger.info(f"  ℹ️  Free Plan: 500 requests/month, 30-min delay")
    logger.info(f"{'='*80}")


if __name__ == '__main__':
    asyncio.run(test_mediastack())
