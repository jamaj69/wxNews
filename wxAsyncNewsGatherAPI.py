#!/usr/bin/env python3
"""
wxAsyncNewsGather with FastAPI Integration
Runs news collection and API server in separate async tasks
"""

from __future__ import print_function

import asyncio
import logging
import sys
import os
import time
from contextlib import asynccontextmanager
from typing import Optional, List, cast

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from decouple import config
from sqlalchemy import create_engine, MetaData, Table, select, func, text, Engine, literal_column
from sqlalchemy.dialects.sqlite import insert

# Import the existing news gather class
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
API_PORT = int(config('NEWS_API_PORT', default=8765))
API_HOST = config('NEWS_API_HOST', default='0.0.0.0')
MAX_ARTICLES = 200

# Global variables for sharing state
news_gather_task: Optional[asyncio.Task] = None
db_engine: Optional[Engine] = None
gm_articles: Optional[Table] = None
gm_sources: Optional[Table] = None

def get_db_path():
    """Get database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path

def init_database():
    """Initialize database connection"""
    global db_engine, gm_articles, gm_sources
    
    db_path = get_db_path()
    db_engine = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False},
        pool_pre_ping=True
    )
    
    meta = MetaData()
    gm_articles = Table('gm_articles', meta, autoload_with=db_engine)
    gm_sources = Table('gm_sources', meta, autoload_with=db_engine)
    
    logger.info(f"📊 Database initialized: {db_path}")

async def run_news_collector():
    """Run the news collection service"""
    logger.info("📰 Starting news collector service...")
    
    gatherer = None
    try:
        # Import the news gather module
        from wxAsyncNewsGather import NewsGather
        
        # Get current event loop
        loop = asyncio.get_running_loop()
        
        # Create news gatherer
        gatherer = NewsGather(loop)
        
        logger.info("🚀 Starting all news collectors in parallel...")
        
        # Create tasks for all three collectors
        tasks = [
            asyncio.create_task(gatherer.collect_newsapi()),
            asyncio.create_task(gatherer.collect_rss_feeds()),
            asyncio.create_task(gatherer.collect_mediastack())
        ]
        
        # Wait for all tasks to complete (they run indefinitely)
        await asyncio.gather(*tasks, return_exceptions=True)
        
    except asyncio.CancelledError:
        logger.info("🛑 News collector tasks cancelled")
        if gatherer is not None:
            gatherer.shutdown()
        raise
    except Exception as e:
        logger.error(f"❌ News collector error: {e}", exc_info=True)
        if gatherer is not None:
            gatherer.shutdown()
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI app"""
    global news_gather_task
    
    # Startup
    logger.info("🚀 Starting wxAsyncNewsGather with FastAPI...")
    init_database()
    
    # Start news collector in background task
    news_gather_task = asyncio.create_task(run_news_collector())
    logger.info("✅ News collector task started")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    if news_gather_task and not news_gather_task.done():
        news_gather_task.cancel()
        try:
            await news_gather_task
        except asyncio.CancelledError:
            pass
    logger.info("✅ Shutdown complete")

# Create FastAPI app
app = FastAPI(
    title="wxNews API",
    description="Real-time news updates API with timestamp-based queries",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """API documentation"""
    return {
        "name": "wxNews API",
        "version": "2.0.0",
        "status": "running",
        "collector_status": "active" if news_gather_task and not news_gather_task.done() else "stopped",
        "endpoints": {
            "GET /api/health": "Health check",
            "GET /api/articles": "Get articles since timestamp",
            "GET /api/latest_timestamp": "Get latest insertion timestamp",
            "GET /api/sources": "Get available news sources",
            "GET /api/stats": "Get collection statistics"
        },
        "documentation": "/docs"
    }

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "timestamp": int(time.time() * 1000),
        "version": "2.0.0",
        "collector_running": news_gather_task and not news_gather_task.done(),
        "database": "connected"
    }

@app.get("/api/articles")
async def get_articles(
    since: int = Query(..., description="Timestamp in milliseconds"),
    limit: int = Query(100, ge=1, le=MAX_ARTICLES, description="Maximum articles to return"),
    sources: Optional[str] = Query(None, description="Comma-separated source IDs")
):
    """
    Get articles inserted after a specific timestamp
    
    - **since**: Required timestamp in milliseconds
    - **limit**: Maximum number of articles (default: 100, max: 200)
    - **sources**: Optional comma-separated list of source IDs
    """
    if db_engine is None or gm_articles is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    # Type narrowing with local variables
    engine = cast(Engine, db_engine)
    articles_table = cast(Table, gm_articles)
    
    try:
        # Get current time for filtering future timestamps
        import time
        current_time_ms = int(time.time() * 1000)
        
        # Build query
        query = select(
            articles_table.c.id_article,
            articles_table.c.id_source,
            articles_table.c.author,
            articles_table.c.title,
            articles_table.c.description,
            articles_table.c.url,
            articles_table.c.urlToImage,
            articles_table.c.publishedAt,
            articles_table.c.published_at_gmt,
            articles_table.c.inserted_at_ms
        ).where(
            articles_table.c.inserted_at_ms > since
        ).where(
            # Filter future inserted_at_ms timestamps (data integrity protection)
            articles_table.c.inserted_at_ms <= current_time_ms
        ).where(
            # CRITICAL: Never return articles with future timestamps (not even 1 second)
            # This ensures clients never see articles before they are published
            # Must convert published_at_gmt (ISO format with 'T') to datetime for correct comparison
            (articles_table.c.published_at_gmt.is_(None)) | 
            (literal_column("datetime(published_at_gmt)") <= literal_column("datetime('now')"))
        )
        
        # Add source filter if provided
        if sources:
            source_list = [s.strip() for s in sources.split(',') if s.strip()]
            if source_list:
                query = query.where(articles_table.c.id_source.in_(source_list))
        
        query = query.order_by(articles_table.c.inserted_at_ms.desc()).limit(limit)
        
        # Execute query
        with engine.connect() as conn:
            result = conn.execute(query)
            rows = result.fetchall()
        
        # Convert to list of dicts
        articles = []
        for row in rows:
            articles.append({
                'id_article': row[0],
                'id_source': row[1],
                'author': row[2],
                'title': row[3],
                'description': row[4],
                'url': row[5],
                'urlToImage': row[6],
                'publishedAt': row[7],
                'published_at_gmt': row[8],
                'inserted_at_ms': row[9]
            })
        
        # Get latest timestamp
        latest_ts = articles[0]['inserted_at_ms'] if articles else since
        
        return {
            'success': True,
            'count': len(articles),
            'since': since,
            'latest_timestamp': latest_ts,
            'articles': articles,
            'timestamp': int(time.time() * 1000)
        }
        
    except Exception as e:
        logger.error(f"Error fetching articles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/latest_timestamp")
async def get_latest_timestamp():
    """Get the latest insertion timestamp"""
    if db_engine is None or gm_articles is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    # Type narrowing with local variables
    engine = cast(Engine, db_engine)
    articles_table = cast(Table, gm_articles)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(
                select(
                    func.max(articles_table.c.inserted_at_ms).label('latest_ts'),
                    func.count().label('total')
                ).where(articles_table.c.inserted_at_ms.isnot(None))
            )
            row = result.fetchone()
        
        if row is None:
            return {
                'success': True,
                'latest_timestamp': 0,
                'total_articles': 0,
                'timestamp': int(time.time() * 1000)
            }
        
        return {
            'success': True,
            'latest_timestamp': row[0] or 0,
            'total_articles': row[1] or 0,
            'timestamp': int(time.time() * 1000)
        }
    except Exception as e:
        logger.error(f"Error getting latest timestamp: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sources")
async def get_sources():
    """Get list of available news sources"""
    if db_engine is None or gm_articles is None or gm_sources is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    # Type narrowing with local variables
    engine = cast(Engine, db_engine)
    articles_table = cast(Table, gm_articles)
    sources_table = cast(Table, gm_sources)
    
    try:
        query = select(
            sources_table.c.id_source,
            sources_table.c.name,
            sources_table.c.category,
            sources_table.c.language,
            func.count(articles_table.c.id_article).label('article_count')
        ).select_from(
            sources_table.outerjoin(
                articles_table,
                sources_table.c.id_source == articles_table.c.id_source
            )
        ).group_by(
            sources_table.c.id_source
        ).having(
            func.count(articles_table.c.id_article) > 0
        ).order_by(
            sources_table.c.name
        )
        
        with engine.connect() as conn:
            result = conn.execute(query)
            rows = result.fetchall()
        
        sources = []
        for row in rows:
            sources.append({
                'id_source': row[0],
                'name': row[1],
                'category': row[2],
                'language': row[3],
                'article_count': row[4]
            })
        
        return {
            'success': True,
            'count': len(sources),
            'sources': sources
        }
    except Exception as e:
        logger.error(f"Error getting sources: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
async def get_stats():
    """Get collection statistics"""
    if db_engine is None or gm_articles is None or gm_sources is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    # Type narrowing with local variables
    engine = cast(Engine, db_engine)
    articles_table = cast(Table, gm_articles)
    sources_table = cast(Table, gm_sources)
    
    try:
        with engine.connect() as conn:
            # Total articles
            total_result = conn.execute(
                select(func.count()).select_from(articles_table)
            )
            total_articles = total_result.scalar()
            
            # Articles in last 24 hours
            yesterday_ts = int((time.time() - 86400) * 1000)
            recent_result = conn.execute(
                select(func.count()).select_from(articles_table).where(
                    articles_table.c.inserted_at_ms > yesterday_ts
                )
            )
            articles_24h = recent_result.scalar()
            
            # Articles in last hour
            hour_ago_ts = int((time.time() - 3600) * 1000)
            hour_result = conn.execute(
                select(func.count()).select_from(articles_table).where(
                    articles_table.c.inserted_at_ms > hour_ago_ts
                )
            )
            articles_1h = hour_result.scalar()
            
            # Total sources
            sources_result = conn.execute(
                select(func.count()).select_from(sources_table)
            )
            total_sources = sources_result.scalar()
            
            # Top sources by article count (last 24h)
            top_sources_result = conn.execute(
                select(
                    articles_table.c.id_source,
                    sources_table.c.name,
                    func.count().label('count')
                ).select_from(
                    articles_table.join(
                        sources_table,
                        articles_table.c.id_source == sources_table.c.id_source
                    )
                ).where(
                    articles_table.c.inserted_at_ms > yesterday_ts
                ).group_by(
                    articles_table.c.id_source
                ).order_by(
                    text('count DESC')
                ).limit(10)
            )
            top_sources = [
                {'id_source': row[0], 'name': row[1], 'count': row[2]}
                for row in top_sources_result.fetchall()
            ]
        
        return {
            'success': True,
            'total_articles': total_articles,
            'articles_last_24h': articles_24h,
            'articles_last_hour': articles_1h,
            'total_sources': total_sources,
            'collection_rate_per_hour': round(articles_1h, 1) if articles_1h else 0.0,
            'top_sources_24h': top_sources,
            'timestamp': int(time.time() * 1000)
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def main():
    """Main entry point"""
    print(f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║        wxAsyncNewsGather with FastAPI Integration         ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  API Server: http://{API_HOST}:{API_PORT:<40} ║
    ║  Database: {get_db_path():<46} ║
    ║                                                            ║
    ║  Services:                                                 ║
    ║    • News Collector (async task)                           ║
    ║    • FastAPI Server (async task)                           ║
    ║                                                            ║
    ║  API Endpoints:                                            ║
    ║    • GET  /                    - API info                  ║
    ║    • GET  /docs                - Interactive docs          ║
    ║    • GET  /api/health          - Health check              ║
    ║    • GET  /api/articles        - Get articles              ║
    ║    • GET  /api/latest_timestamp - Latest timestamp         ║
    ║    • GET  /api/sources         - List sources              ║
    ║    • GET  /api/stats           - Collection stats          ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Run uvicorn server
    uvicorn.run(
        app,
        host=str(API_HOST),
        port=API_PORT,
        log_level="info",
        access_log=True
    )

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
