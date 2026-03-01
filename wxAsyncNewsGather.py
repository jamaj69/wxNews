#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec  2 16:21:25 2019

@author: jamaj
"""

from __future__ import print_function

import logging
import sys
from multiprocessing import Queue
import re
import subprocess
import tempfile

import urllib.request 
import json
import webbrowser

import asyncio, aiohttp

from asyncio.events import get_event_loop
import time
import base64
import zlib

from sqlalchemy import (create_engine, Table, Column, Integer, 
    String, MetaData, Text)
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.sqlite import insert
import os
from urllib.parse import urlparse
import feedparser
from datetime import datetime, timezone
from dateutil import parser as dateutil_parser
import pytz

# Load credentials from environment
from decouple import config

# Import article content fetcher
from article_fetcher import fetch_article_content
import signal

# NewsAPI Configuration
API_KEY1 = config('NEWS_API_KEY_1', cast=str)
API_KEY2 = config('NEWS_API_KEY_2', cast=str)
NEWSAPI_CYCLE_INTERVAL = int(config('NEWSAPI_CYCLE_INTERVAL', default=600))  # 10 minutes

# RSS Configuration
RSS_TIMEOUT = int(config('RSS_TIMEOUT', default=15))
RSS_MAX_CONCURRENT = int(config('RSS_MAX_CONCURRENT', default=10))
RSS_BATCH_SIZE = int(config('RSS_BATCH_SIZE', default=20))
RSS_CYCLE_INTERVAL = int(config('RSS_CYCLE_INTERVAL', default=900))  # 15 minutes

# MediaStack Configuration
MEDIASTACK_API_KEY = config('MEDIASTACK_API_KEY', cast=str)
MEDIASTACK_BASE_URL = config(
    'MEDIASTACK_BASE_URL',
    default='https://api.mediastack.com/v1/news',
    cast=str,
)
MEDIASTACK_RATE_DELAY = 20  # Delay between requests (seconds) - 3 requests/minute
MEDIASTACK_CYCLE_INTERVAL = int(config('MEDIASTACK_CYCLE_INTERVAL', default=3600))  # 60 minutes

# Content Enrichment Configuration
ENRICH_MISSING_CONTENT = config('ENRICH_MISSING_CONTENT', default=True, cast=bool)
ENRICH_TIMEOUT = int(config('ENRICH_TIMEOUT', default=10))

# Basic browser-like headers improve compatibility with feeds/CDNs
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
BASIC_HTTP_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": (
        "application/rss+xml, application/atom+xml, application/rdf+xml, "
        "application/xml;q=0.95, text/xml;q=0.9, "
        "application/json;q=0.8, text/html;q=0.7, text/plain;q=0.6, */*;q=0.5"
    ),
    "Accept-Language": (
        "en-US,en;q=0.95, pt-BR,pt;q=0.9, es-ES,es;q=0.85, "
        "fr-FR,fr;q=0.8, de-DE,de;q=0.75, it-IT,it;q=0.7"
    ),
    "Cache-Control": "max-age=0",
}


def url_encode(url):
    return base64.urlsafe_b64encode(zlib.compress(url.encode('utf-8')))[15:31]



def dbCredentials():
    """Return SQLite database path"""
    db_path = config('DB_PATH', default='predator_news.db', cast=str)
    # Make path absolute if relative
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path


def as_text(value):
    """Return a safe string for loosely-typed feed/API fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(as_text(item) for item in value if item is not None)
    return str(value)


# Country code to timezone mapping (most common timezone for each country)
COUNTRY_TIMEZONES = {
    'us': 'America/New_York', 'gb': 'Europe/London', 'ca': 'America/Toronto',
    'au': 'Australia/Sydney', 'de': 'Europe/Berlin', 'fr': 'Europe/Paris',
    'it': 'Europe/Rome', 'es': 'Europe/Madrid', 'jp': 'Asia/Tokyo',
    'cn': 'Asia/Shanghai', 'kr': 'Asia/Seoul', 'in': 'Asia/Kolkata',
    'br': 'America/Sao_Paulo', 'mx': 'America/Mexico_City', 'ru': 'Europe/Moscow',
    'za': 'Africa/Johannesburg', 'sg': 'Asia/Singapore', 'hk': 'Asia/Hong_Kong',
    'nz': 'Pacific/Auckland', 'ar': 'America/Argentina/Buenos_Aires',
    'cl': 'America/Santiago', 'co': 'America/Bogota', 'nl': 'Europe/Amsterdam',
    'se': 'Europe/Stockholm', 'no': 'Europe/Oslo', 'dk': 'Europe/Copenhagen',
    'fi': 'Europe/Helsinki', 'pl': 'Europe/Warsaw', 'tr': 'Europe/Istanbul',
    'il': 'Asia/Jerusalem', 'ae': 'Asia/Dubai', 'sa': 'Asia/Riyadh',
    'eg': 'Africa/Cairo', 'ng': 'Africa/Lagos', 'ke': 'Africa/Nairobi',
    'th': 'Asia/Bangkok', 'vn': 'Asia/Ho_Chi_Minh', 'id': 'Asia/Jakarta',
    'ph': 'Asia/Manila', 'my': 'Asia/Kuala_Lumpur', 'pk': 'Asia/Karachi',
    'bd': 'Asia/Dhaka', 'ua': 'Europe/Kiev', 'ro': 'Europe/Bucharest',
    'cz': 'Europe/Prague', 'at': 'Europe/Vienna', 'ch': 'Europe/Zurich',
    'be': 'Europe/Brussels', 'pt': 'Europe/Lisbon', 'gr': 'Europe/Athens',
    'ie': 'Europe/Dublin', 'nz': 'Pacific/Auckland', 'tw': 'Asia/Taipei'
}


def normalize_timestamp_to_utc(timestamp_str):
    """
    Normalize a timestamp string to UTC (GMT+0) using timezone info from the timestamp itself.
    
    Args:
        timestamp_str: Timestamp string with timezone info (ISO, RFC 2822, etc.)
    
    Returns:
        ISO format UTC timestamp string, or current UTC time if parsing fails
    """
    if not timestamp_str or timestamp_str.strip() == '':
        return datetime.now(timezone.utc).isoformat()
    
    # Mapping of common timezone abbreviations to UTC offsets (in seconds)
    # This prevents UnknownTimezoneWarning from dateutil
    tzinfos = {
        'EDT': -4 * 3600,    # Eastern Daylight Time (UTC-4)
        'EST': -5 * 3600,    # Eastern Standard Time (UTC-5)
        'CDT': -5 * 3600,    # Central Daylight Time (UTC-5)
        'CST': -6 * 3600,    # Central Standard Time (UTC-6)
        'MDT': -6 * 3600,    # Mountain Daylight Time (UTC-6)
        'MST': -7 * 3600,    # Mountain Standard Time (UTC-7)
        'PDT': -7 * 3600,    # Pacific Daylight Time (UTC-7)
        'PST': -8 * 3600,    # Pacific Standard Time (UTC-8)
        'AKDT': -8 * 3600,   # Alaska Daylight Time (UTC-8)
        'AKST': -9 * 3600,   # Alaska Standard Time (UTC-9)
        'HST': -10 * 3600,   # Hawaii Standard Time (UTC-10)
        'BST': 1 * 3600,     # British Summer Time (UTC+1)
        'CEST': 2 * 3600,    # Central European Summer Time (UTC+2)
        'CET': 1 * 3600,     # Central European Time (UTC+1)
        'EEST': 3 * 3600,    # Eastern European Summer Time (UTC+3)
        'EET': 2 * 3600,     # Eastern European Time (UTC+2)
        'IST': 5.5 * 3600,   # Indian Standard Time (UTC+5:30)
        'JST': 9 * 3600,     # Japan Standard Time (UTC+9)
        'KST': 9 * 3600,     # Korea Standard Time (UTC+9)
        'AEST': 10 * 3600,   # Australian Eastern Standard Time (UTC+10)
        'AEDT': 11 * 3600,   # Australian Eastern Daylight Time (UTC+11)
        'AWST': 8 * 3600,    # Australian Western Standard Time (UTC+8)
        'NZST': 12 * 3600,   # New Zealand Standard Time (UTC+12)
        'NZDT': 13 * 3600,   # New Zealand Daylight Time (UTC+13)
    }
    
    try:
        # Parse the timestamp with dateutil (handles most formats and extracts timezone)
        parsed_dt = dateutil_parser.parse(timestamp_str, tzinfos=tzinfos)
        
        # If no timezone info in the timestamp, assume it's already UTC
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        
        # Convert to UTC
        utc_dt = parsed_dt.astimezone(timezone.utc)
        
        # Return ISO format without microseconds for consistency
        return utc_dt.replace(microsecond=0).isoformat()
        
    except Exception as e:
        # If parsing fails, return current UTC time
        logging.debug(f"Failed to parse timestamp '{timestamp_str}': {e}")
        return datetime.now(timezone.utc).isoformat()




class NewsGather():
    def __init__(self, loop):
        self.logger = logging.getLogger(__name__)
        self.sources = dict()
        self.loop = loop
        self.db_lock = asyncio.Lock()  # Lock para serializar inserções SQLite
        self.shutdown_flag = False  # Flag para shutdown gracioso
        
        # API key rotation for NewsAPI
        self.newsapi_keys = [API_KEY1, API_KEY2]
        self.current_newsapi_key_index = 0
   
        self.logger.info("Initializing NewsGather...")
        self.logger.debug("Creating URL queue")
        self.url_queue = Queue()   
       
        self.logger.info("Opening database connection")
        self.eng = self.dbOpen()
        self.meta = MetaData()        
        self.gm_sources = Table('gm_sources', self.meta, autoload_with=self.eng) 
        self.gm_articles = Table('gm_articles', self.meta, autoload_with=self.eng) 
        
        self.logger.info("Loading existing articles from database")
        self.sources = self.InitArticles(self.eng, self.meta, self.gm_sources,self.gm_articles)
        self.logger.info(f"Loaded {len(self.sources)} sources from database")
    
    def shutdown(self):
        """
        Gracefully shutdown the application:
        - Close database connections
        - Clean up resources
        Note: shutdown_flag should already be set before calling this
        """
        self.logger.info("🛑 Shutting down NewsGather...")
        
        try:
            if hasattr(self, 'eng') and self.eng:
                self.logger.info("Closing database connection...")
                self.eng.dispose()
                self.logger.info("✅ Database connection closed")
        except Exception as e:
            self.logger.error(f"Error closing database: {e}")
        
        self.logger.info("✅ Shutdown complete")

    def _build_http_headers(self, url: str) -> dict:
        headers = dict(BASIC_HTTP_HEADERS)
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            if parsed.netloc.endswith("indianexpress.com"):
                headers["Referer"] = "https://indianexpress.com/rss/"
            else:
                headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
        return headers

    def _looks_like_feed_content_type(self, content_type: str) -> bool:
        ct = (content_type or "").lower()
        if not ct:
            return False
        allowed_markers = (
            "application/rss+xml",
            "application/atom+xml",
            "application/xml",
            "text/xml",
            "application/rdf+xml",
        )
        return any(marker in ct for marker in allowed_markers)

    def _looks_like_feed_body(self, text: str) -> bool:
        sample = (text or "")[:2000].lower()
        return any(tag in sample for tag in ("<?xml", "<rss", "<feed", "<rdf:rdf"))

    def _fetch_rss_with_curl(self, url: str, timeout_seconds: int):
        headers = self._build_http_headers(url)
        with tempfile.NamedTemporaryFile(delete=False) as hdr_tmp:
            hdr_path = hdr_tmp.name
        with tempfile.NamedTemporaryFile(delete=False) as body_tmp:
            body_path = body_tmp.name
        try:
            cmd = [
                "curl",
                "-sS",
                "-L",
                "--compressed",
                "--max-time",
                str(timeout_seconds),
                "-D",
                hdr_path,
                "-o",
                body_path,
                url,
            ]
            for key, value in headers.items():
                cmd.extend(["-H", f"{key}: {value}"])

            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 5,
            )
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout or "curl failed").strip())

            header_text = open(hdr_path, "r", encoding="latin-1", errors="replace").read()
            body_bytes = open(body_path, "rb").read()

            status = 0
            content_type = ""
            blocks = [b for b in re.split(r"\r?\n\r?\n", header_text) if b.strip()]
            for block in blocks:
                lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
                if not lines or not lines[0].startswith("HTTP/"):
                    continue
                first = lines[0].split()
                if len(first) >= 2 and first[1].isdigit():
                    status = int(first[1])
                for line in lines[1:]:
                    if line.lower().startswith("content-type:"):
                        content_type = line.split(":", 1)[1].strip()

            charset = "utf-8"
            m = re.search(r"charset=([A-Za-z0-9._-]+)", content_type or "", flags=re.I)
            if m:
                charset = m.group(1)
            try:
                text = body_bytes.decode(charset, errors="replace")
            except Exception:
                text = body_bytes.decode("utf-8", errors="replace")

            return status, content_type, text
        finally:
            try:
                os.unlink(hdr_path)
            except Exception:
                pass
            try:
                os.unlink(body_path)
            except Exception:
                pass

    async def _fetch_rss_content(self, session, rss_url, timeout_seconds):
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with session.get(
            rss_url,
            timeout=timeout,
            headers=self._build_http_headers(rss_url),
        ) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            text = await response.text()

        if status == 403:
            try:
                status, content_type, text = await asyncio.to_thread(
                    self._fetch_rss_with_curl, rss_url, timeout_seconds
                )
            except Exception as exc:
                self.logger.debug(f"Curl fallback failed for {rss_url}: {exc}")
        return status, content_type, text
    
    def InitArticles(self, eng, meta, gm_sources, gm_articles):
        """
        Load only sources from database (not articles).
        Article deduplication is handled by SQLite on_conflict_do_nothing().
        Loading all articles wastes RAM and slows initialization.
        """
        self.logger.debug("InitArticles: Loading sources from database")
        sources = dict()
        
        with eng.connect() as con:
            stm = select(gm_sources)
            rs = con.execute(stm) 
            source_count = 0
            for source in rs.fetchall():
                source_id = source[0]
                source_count += 1
                
                # Only load source metadata, not individual articles
                # Articles are managed by SQLite with on_conflict_do_nothing()
                sources[source_id] = { 
                        'id_source': source_id,
                        'name': source[1],
                        'description': source[2],
                        'url': source[3],
                        'category': source[4],
                        'language': source[5],
                        'country': source[6],
                        'articles': {}  # Empty dict - articles checked via SQLite, not memory
                     }

            self.logger.info(f"InitArticles: Loaded {source_count} sources (articles managed by SQLite)")
        return sources

    # ========================================================================
    # LEGACY METHODS - Not used in new parallel architecture
    # Kept for reference only
    # ========================================================================
    
    # def UpdateNews(self):
    #     """LEGACY: Replaced by individual collector methods running in parallel"""
    #     pass
    
    # async def async_getALLNews(self):
    #     """LEGACY: Replaced by collect_newsapi() running in parallel loop"""
    #     pass

    def dbOpen(self):    
        db_path = dbCredentials()
        self.logger.info(f"Opening SQLite database: {db_path}")
        # SQLite connection string with WAL mode and increased timeout for concurrent writes
        eng = create_engine(
            f'sqlite:///{db_path}',
            connect_args={
                'timeout': 60,  # Increased from 30 to 60 seconds
                'check_same_thread': False,
                'isolation_level': None  # Autocommit mode for better concurrency
            },
            pool_pre_ping=True,
            pool_size=10,  # Connection pool to avoid creating new connections
            max_overflow=20
        )
        
        # Enable WAL mode for better concurrent access (allows multiple readers + 1 writer)
        with eng.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))  # Faster writes, still safe
            conn.execute(text("PRAGMA busy_timeout=60000"))  # 60 second busy timeout
            conn.commit()
            self.logger.info("✅ SQLite WAL mode enabled for concurrent access")
    #    cur = eng.connect()  
    
        self.logger.debug("Creating metadata and tables if not exist")
        meta = MetaData()
        gm_sources = Table(
            'gm_sources', meta,
             Column('id_source', Text, primary_key=True),
             Column('name', Text),
             Column('description', Text),
             Column('url', Text),
             Column('category', Text),
             Column('language', Text),
             Column('country', Text)
        )
        gm_sources.create(bind=eng, checkfirst=True)
        self.logger.debug("Table gm_sources ready")
        
        meta = MetaData()
        gm_articles = Table(
            'gm_articles', meta,
            Column('id_article', Text, primary_key=True),
            Column('id_source', Text),
            Column('author', Text),
            Column('title', Text),
            Column('description', Text),
            Column('url', Text),
            Column('urlToImage' , Text),
            Column('publishedAt', Text),
            Column('published_at_gmt', Text),  # Normalized UTC version
            Column('content', Text)
        )
        gm_articles.create(bind=eng, checkfirst=True)
        self.logger.debug("Table gm_articles ready")
        
        # Add fetch_blocked columns if they don't exist (migration)
        try:
            with eng.connect() as conn:
                # Check if columns exist by querying SQLite schema
                result = conn.execute(text("PRAGMA table_info(gm_sources)")).fetchall()
                column_names = [row[1] for row in result]  # row[1] is column name
                
                if 'fetch_blocked' in column_names:
                    self.logger.debug("Blocklist columns already exist")
                else:
                    # Columns don't exist, add them
                    self.logger.info("Adding fetch_blocked and blocked_count columns to gm_sources")
                    conn.execute(text('ALTER TABLE gm_sources ADD COLUMN fetch_blocked INTEGER DEFAULT 0'))
                    conn.execute(text('ALTER TABLE gm_sources ADD COLUMN blocked_count INTEGER DEFAULT 0'))
                    conn.commit()
                    self.logger.info("✅ Blocklist columns added successfully")
        except Exception as e:
            # Log at DEBUG level to avoid noise
            self.logger.debug(f"Error with blocklist columns: {e}")
        
        # Add published_at_gmt column to gm_articles if it doesn't exist (migration)
        try:
            with eng.connect() as conn:
                # Check if column exists by querying SQLite schema
                result = conn.execute(text("PRAGMA table_info(gm_articles)")).fetchall()
                column_names = [row[1] for row in result]  # row[1] is column name
                
                if 'published_at_gmt' not in column_names:
                    self.logger.info("Adding published_at_gmt column to gm_articles for UTC normalization")
                    conn.execute(text('ALTER TABLE gm_articles ADD COLUMN published_at_gmt TEXT'))
                    conn.commit()
                    self.logger.info("✅ published_at_gmt column added successfully")
                else:
                    self.logger.debug("published_at_gmt column already exists")
        except Exception as e:
            self.logger.debug(f"Error with published_at_gmt column: {e}")
        
        # Create index on published_at_gmt DESC for efficient querying of most recent news
        try:
            with eng.connect() as conn:
                # Check if index exists
                result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_articles_published_gmt_desc'")).fetchone()
                
                if not result:
                    self.logger.info("Creating index on published_at_gmt for fast recent news queries")
                    conn.execute(text('CREATE INDEX idx_articles_published_gmt_desc ON gm_articles(published_at_gmt DESC)'))
                    conn.commit()
                    self.logger.info("✅ Index idx_articles_published_gmt_desc created successfully")
                else:
                    self.logger.debug("Index on published_at_gmt already exists")
        except Exception as e:
            self.logger.debug(f"Error with published_at_gmt index: {e}")
        
        self.logger.info("Database initialization complete")
        return eng
        

    async def track(self):
        """Legacy Twitter stream hook kept as a no-op placeholder."""
        self.logger.debug("track() is disabled in this build")

    # async def async_getALLNews(self):
    #     """LEGACY: Replaced by collect_newsapi() running in parallel loop"""
    #     # This method has been replaced by the new architecture
    #     pass

    async def discover_rss_feed(self, session, domain, source_name):
        """
        Try to discover RSS feed for a domain.
        Tests common RSS URL patterns.
        """
        common_patterns = [
            f'https://{domain}/feed/',
            f'https://{domain}/rss',
            f'https://{domain}/rss.xml',
            f'https://{domain}/feed',
            f'https://{domain}/feeds/posts/default',  # Blogger
            f'https://{domain}/index.xml',
            f'https://{domain}/atom.xml',
            f'http://{domain}/feed/',
            f'http://{domain}/rss',
        ]
        
        for rss_url in common_patterns:
            try:
                status, content_type, content = await self._fetch_rss_content(session, rss_url, 10)
                if status == 200 and (
                    self._looks_like_feed_content_type(content_type) or self._looks_like_feed_body(content)
                ):
                    if any(tag in content[:1000] for tag in ['<rss', '<feed', '<channel']):
                        self.logger.info(f"📡 Discovered RSS for {source_name}: {rss_url}")
                        return rss_url
            except Exception:
                continue
        
        return None
    
    async def extract_rss_feed_name(self, session, rss_url):
        """
        Extract feed title from RSS feed URL.
        Used when source name is empty/missing.
        """
        try:
            status, content_type, content = await self._fetch_rss_content(session, rss_url, 10)
            if status != 200:
                return None
            if not self._looks_like_feed_content_type(content_type) and not self._looks_like_feed_body(content):
                return None

            try:
                feed = feedparser.parse(content)
            except (AssertionError, ValueError, Exception) as parse_err:
                # feedparser can raise AssertionError on malformed HTML/XML
                self.logger.debug(f"Parser error for {rss_url}: {parse_err}")
                return None
                
            feed_info = getattr(feed, "feed", {})
            if isinstance(feed_info, dict):
                title = as_text(feed_info.get("title", "")).strip()
            else:
                title = as_text(getattr(feed_info, "title", "")).strip()
            if title:
                self.logger.debug(f"Extracted feed name: {title}")
                return title
            return None
        except Exception as e:
            self.logger.debug(f"Failed to extract feed name from {rss_url}: {e}")
            return None
    
    async def register_rss_source(self, session, source_id, source_name, source_url):
        """
        Check if source has RSS feed and register it if found.
        """
        # Check if already registered as RSS
        rss_id = f'rss-{source_id}'
        if rss_id in self.sources:
            return  # Already registered
        
        try:
            # Extract domain from source URL
            if not source_url or source_url.strip() == '':
                return
            
            parsed = urlparse(source_url)
            domain = parsed.netloc or parsed.path
            if not domain:
                return
            
            # Try to discover RSS feed
            rss_url = await self.discover_rss_feed(session, domain, source_name)
            if rss_url:
                # Extract feed title if source_name is empty
                if not source_name or source_name.strip() == '':
                    source_name = await self.extract_rss_feed_name(session, rss_url)
                    if not source_name:
                        # Fallback: generate from domain
                        source_name = domain.replace('www.', '').split('.')[0].upper()
                
                # Register as new RSS source
                new_rss_source = {
                    'id_source': rss_id,
                    'name': source_name,
                    'url': rss_url,
                    'description': f'Auto-discovered from NewsAPI',
                    'category': 'general',
                    'language': 'en',
                    'country': ''
                }
                
                async with self.db_lock:
                    with self.eng.connect() as conn:
                        try:
                            ins = insert(self.gm_sources).values(**new_rss_source)
                            ins = ins.on_conflict_do_nothing()
                            result = conn.execute(ins)
                            conn.commit()
                            if result.rowcount > 0:
                                self.sources[rss_id] = {**new_rss_source, 'articles': {}}
                                self.logger.info(f"✅ Registered RSS source: {source_name} -> {rss_url}")
                        except Exception as e:
                            self.logger.error(f"Failed to register RSS source {source_name}: {e}")
                            conn.rollback()
        except Exception as e:
            self.logger.debug(f"Could not discover RSS for {source_name}: {e}")
    
    async def collect_newsapi(self):
        """
        Collect articles from NewsAPI in continuous loop with API key rotation.
        Languages: EN, PT, ES, IT
        """
        self.logger.info("🗞️  NewsAPI collector started")
        cycle_count = 0
        
        # Language to API key mapping for rotation
        languages = ['en', 'pt', 'es', 'it']
        
        try:
            while not self.shutdown_flag:
                cycle_count += 1
                self.logger.info(f"📰 NewsAPI Cycle {cycle_count} starting...")
                
                async with aiohttp.ClientSession() as session:
                    for lang in languages:
                        if self.shutdown_flag:
                            break
                        
                        # Rotate API key
                        api_key = self.newsapi_keys[self.current_newsapi_key_index]
                        self.current_newsapi_key_index = (self.current_newsapi_key_index + 1) % len(self.newsapi_keys)
                        
                        url = f"https://newsapi.org/v2/top-headlines?language={lang}&pageSize=100&apiKey={api_key}"
                        
                        self.logger.info(f"Fetching NewsAPI [{lang.upper()}] (key #{self.current_newsapi_key_index})...")
                        
                        try:
                            async with session.get(url, headers=self._build_http_headers(url)) as response:
                                if response.status != 200:
                                    self.logger.warning(f"HTTP {response.status} for NewsAPI {lang}")
                                    continue
                                
                                response_text = await response.text()
                                JSON_object = json.loads(response_text)
                                
                                if JSON_object.get('status') != 'ok':
                                    self.logger.error(f"NewsAPI error [{lang}]: {JSON_object.get('message')}")
                                    continue
                                
                                articles = JSON_object.get("articles", [])
                                self.logger.info(f"Processing {len(articles)} articles for {lang}")
                                
                                articles_inserted = 0
                                articles_skipped = 0
                                sources_added = 0
                                
                                for article in articles:
                                    if self.shutdown_flag:
                                        break
                                    
                                    await asyncio.sleep(0)  # cooperate with other tasks
                                    
                                    article_source = article['source']
                                    article_source_id = article_source['id']
                                    article_source_name = article_source['name']
                                    source_id = article_source_name if article_source_id is None else article_source_id
                                    source_name = article_source_name
                                    article_author = article['author']
                                    article_title = article['title']
                                    
                                    # Clean title: normalize whitespace
                                    if article_title:
                                        article_title = ' '.join(article_title.split())
                                    
                                    article_description = article['description']
                                    article_url = article['url']
                                    article_urlToImage = article['urlToImage']
                                    article_publishedAt = article['publishedAt']  # Keep original with timezone
                                    article_content = article['content']
                                    
                                    # Create normalized UTC version
                                    article_publishedAt_gmt = normalize_timestamp_to_utc(article_publishedAt)
                                    
                                    article_key = url_encode(article_title + article_url + article_publishedAt)
                                    
                                    # Try to extract source URL from article URL
                                    if not article_url:
                                        article_url = ''
                                    try:
                                        parsed_url = urlparse(article_url)
                                        inferred_source_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                                    except:
                                        inferred_source_url = ''
                                    
                                    # Add new source if not exists
                                    if source_id not in self.sources:
                                        self.logger.debug(f"New source detected: {source_name} (id: {source_id})")
                                        source_url = inferred_source_url
                                        source_description = ''
                                        
                                        new_source = {
                                            'id_source': source_id,
                                            'name': source_name,
                                            'url': source_url,
                                            'description': source_description,
                                            'category': '',
                                            'country': '',
                                            'language': lang
                                        }
                                        
                                        self.sources[source_id] = {**new_source, 'articles': {}}
                                        
                                        async with self.db_lock:
                                            with self.eng.connect() as conn:
                                                try:
                                                    ins = insert(self.gm_sources).values(**new_source)
                                                    result = conn.execute(ins)
                                                    conn.commit()
                                                    sources_added += 1
                                                    self.logger.info(f"✅ Added source: {source_name}")
                                                    
                                                    # Try to discover RSS feed
                                                    if source_url:
                                                        self.loop.create_task(
                                                            self.register_rss_source(session, source_id, source_name, source_url)
                                                        )
                                                except Exception as e:
                                                    self.logger.error(f"Failed to insert source {source_name}: {e}")
                                                    conn.rollback()
                                    
                                    # Insert article
                                    new_article = {
                                        'id_article': article_key,
                                        'id_source': source_id,
                                        'author': article_author,
                                        'title': article_title,
                                        'description': article_description,
                                        'url': article_url,
                                        'urlToImage': article_urlToImage,
                                        'publishedAt': article_publishedAt,  # Original with timezone
                                        'published_at_gmt': article_publishedAt_gmt,  # Normalized UTC
                                        'content': article_content
                                    }
                                    
                                    # Try to enrich with missing content
                                    await self.enrich_article_content(new_article, source_name, source_id)
                                    
                                    async with self.db_lock:
                                        with self.eng.connect() as conn:
                                            try:
                                                ins = insert(self.gm_articles).values(**new_article)
                                                ins_do_nothing = ins.on_conflict_do_nothing()
                                                result = conn.execute(ins_do_nothing)
                                                conn.commit()
                                                
                                                if result.rowcount > 0:
                                                    articles_inserted += 1
                                                    self.logger.debug(f"✅ [{source_name}] {article_title[:60]}...")
                                                else:
                                                    articles_skipped += 1
                                                    self.logger.debug(f"⏭️  [{source_name}] Already exists: {article_title[:40]}...")
                                                
                                                # No need to cache articles in memory - SQLite handles deduplication
                                            except Exception as e:
                                                self.logger.error(f"Failed to insert article '{article_title[:40]}...': {e}")
                                                conn.rollback()
                                
                                self.logger.info(f"Summary NewsAPI {lang}: {articles_inserted} inserted, {articles_skipped} skipped, {sources_added} new sources")
                        
                        except aiohttp.ClientError as e:
                            self.logger.error(f"Network error fetching NewsAPI {lang}: {e}")
                        except json.JSONDecodeError as e:
                            self.logger.error(f"JSON decode error for NewsAPI {lang}: {e}")
                        except Exception as e:
                            self.logger.error(f"Unexpected error processing NewsAPI {lang}: {e}", exc_info=True)
                
                if not self.shutdown_flag:
                    self.logger.info(f"NewsAPI cycle {cycle_count} complete. Sleeping {NEWSAPI_CYCLE_INTERVAL}s...")
                    await asyncio.sleep(NEWSAPI_CYCLE_INTERVAL)
        except asyncio.CancelledError:
            self.logger.info("🗞️  NewsAPI collector cancelled")
        finally:
            self.logger.info("🗞️  NewsAPI collector stopped")
    
    async def collect_rss_feeds(self):
        """
        Collect articles from all RSS sources in database in continuous loop.
        """
        self.logger.info("📡 RSS collector started")
        cycle_count = 0
        
        try:
            while not self.shutdown_flag:
                cycle_count += 1
                self.logger.info(f"📡 RSS Cycle {cycle_count} starting...")
                
                # Get all RSS sources from database
                rss_sources = []
                with self.eng.connect() as conn:
                    stmt = select(self.gm_sources).where(
                        self.gm_sources.c.id_source.like('rss-%')
                    )
                    results = conn.execute(stmt).fetchall()
                    for row in results:
                        if self.shutdown_flag:
                            break
                        rss_sources.append({
                            'id': row[0],
                            'name': row[1],
                            'url': row[3],
                            'language': row[5] or 'en'
                        })
                
                if not rss_sources:
                    self.logger.info("No RSS sources found in database")
                    if not self.shutdown_flag:
                        self.logger.info(f"RSS: No sources yet. Sleeping {RSS_CYCLE_INTERVAL}s...")
                        await asyncio.sleep(RSS_CYCLE_INTERVAL)
                    continue
                
                self.logger.info(f"Found {len(rss_sources)} RSS sources to process")
                
                # Process feeds with semaphore for concurrency control
                semaphore = asyncio.Semaphore(RSS_MAX_CONCURRENT)
                
                async with aiohttp.ClientSession() as session:
                    # Process in batches
                    for i in range(0, len(rss_sources), RSS_BATCH_SIZE):
                        if self.shutdown_flag:
                            break
                        
                        batch = rss_sources[i:i+RSS_BATCH_SIZE]
                        self.logger.info(f"Processing RSS batch {i//RSS_BATCH_SIZE + 1} ({len(batch)} feeds)...")
                        
                        tasks = [
                            self.process_rss_feed_with_semaphore(session, source, semaphore)
                            for source in batch
                        ]
                        await asyncio.gather(*tasks, return_exceptions=True)
                
                if not self.shutdown_flag:
                    self.logger.info(f"RSS cycle {cycle_count} complete. Sleeping {RSS_CYCLE_INTERVAL}s...")
                    await asyncio.sleep(RSS_CYCLE_INTERVAL)
        except asyncio.CancelledError:
            self.logger.info("📡 RSS collector cancelled")
        finally:
            self.logger.info("📡 RSS collector stopped")
    
    async def process_rss_feed_with_semaphore(self, session, source, semaphore):
        """
        Process RSS feed with semaphore control.
        """
        async with semaphore:
            return await self.process_rss_feed(session, source)
    
    async def process_rss_feed(self, session, source):
        """
        Fetch and process a single RSS feed.
        """
        source_id = source['id']
        source_name = source['name']
        rss_url = source['url']
        
        try:
            status, content_type, content = await self._fetch_rss_content(session, rss_url, RSS_TIMEOUT)
            if status != 200:
                self.logger.warning(f"❌ [{source_name}] HTTP {status}")
                return
            if not self._looks_like_feed_content_type(content_type) and not self._looks_like_feed_body(content):
                self.logger.warning(f"❌ [{source_name}] Invalid content type: {content_type}")
                return

            try:
                feed = feedparser.parse(content)
            except (AssertionError, ValueError, Exception) as parse_err:
                # feedparser can raise AssertionError on malformed HTML/XML in marked sections
                self.logger.debug(f"⚠️  [{source_name}] Parser error (malformed feed): {parse_err}")
                return
                
            if not feed.entries:
                self.logger.debug(f"⚠️  [{source_name}] No entries found")
                return
            
            self.logger.debug(f"📥 [{source_name}] Received {len(feed.entries)} entries")
            
            articles_inserted = 0
            articles_skipped = 0
            
            for entry in feed.entries:
                    # Extract article data
                    title = as_text(entry.get('title', ''))
                    # Clean title: normalize whitespace
                    if title:
                        title = ' '.join(title.split())
                    url = as_text(entry.get('link', ''))
                    description = as_text(entry.get('summary', entry.get('description', '')))
                    author = as_text(entry.get('author', ''))
                    published = as_text(entry.get('published', entry.get('updated', '')))  # Original with timezone
                    
                    if not title or not url:
                        continue
                    
                    # Create normalized UTC version
                    published_gmt = normalize_timestamp_to_utc(published)
                    
                    # Generate article key with original timestamp
                    article_key = url_encode(title + url + published)
                    
                    # Create article object
                    new_article = {
                        'id_article': article_key,
                        'id_source': source_id,
                        'author': author,
                        'title': title,
                        'description': description[:500] if description else '',
                        'url': url,
                        'urlToImage': '',
                        'publishedAt': published,  # Original with timezone
                        'published_at_gmt': published_gmt,  # Normalized UTC
                        'content': ''
                    }
                    
                    # Try to enrich with missing content from URL
                    await self.enrich_article_content(new_article, source_name, source['id'])
                    
                    # Insert article
                    async with self.db_lock:
                        with self.eng.connect() as conn:
                            try:
                                ins = insert(self.gm_articles).values(**new_article)
                                ins_do_nothing = ins.on_conflict_do_nothing()
                                result = conn.execute(ins_do_nothing)
                                conn.commit()
                                
                                if result.rowcount > 0:
                                    articles_inserted += 1
                                    if articles_inserted <= 5:  # Log first 5
                                        self.logger.debug(f"  ✅ [{source_name}] {title[:60]}...")
                                else:
                                    articles_skipped += 1
                            except Exception as e:
                                self.logger.error(f"Failed to insert RSS article: {e}")
                                conn.rollback()
                
            if articles_inserted > 0:
                self.logger.debug(f"✅ [{source_name}] {articles_inserted} new, {articles_skipped} existing")
            else:
                self.logger.debug(f"⏭️  [{source_name}] All {articles_skipped} articles already exist")
                    
        except asyncio.TimeoutError:
            self.logger.warning(f"⏱️  [{source_name}] Timeout after {RSS_TIMEOUT}s")
        except Exception as e:
            self.logger.error(f"❌ [{source_name}] Error: {str(e)[:100]}")
    
    async def collect_mediastack(self):
        """
        Collect articles from MediaStack API with rate limiting in continuous loop.
        Free tier: 500 requests/month, ~3-4 requests/minute
        Strategy: Collect PT, ES, IT (EN covered by NewsAPI)
        """
        self.logger.info("🌍 MediaStack collector started")
        cycle_count = 0
        
        # Languages to collect (EN already covered by NewsAPI)
        languages = ['pt', 'es', 'it']
        
        try:
            while not self.shutdown_flag:
                cycle_count += 1
                self.logger.info(f"🌍 MediaStack Cycle {cycle_count} starting...")
                
                stats = {
                    'total_fetched': 0,
                    'inserted': 0,
                    'skipped': 0,
                    'errors': 0
                }
                
                async with aiohttp.ClientSession() as session:
                    for i, language in enumerate(languages):
                        if self.shutdown_flag:
                            break
                        
                        self.logger.info(f"🌍 Collecting MediaStack news for language: {language}")
                        
                        try:
                            # Prepare request
                            params = {
                                'access_key': MEDIASTACK_API_KEY,
                                'languages': language,
                                'limit': 25,  # Collect 25 articles per language
                                'sort': 'published_desc'
                            }
                            
                            # Fetch news
                            async with session.get(
                                MEDIASTACK_BASE_URL, 
                                params=params, 
                                headers=self._build_http_headers(MEDIASTACK_BASE_URL),
                                timeout=aiohttp.ClientTimeout(total=30)
                            ) as response:
                                if response.status == 200:
                                    data = await response.json()
                                    
                                    # Check for API errors
                                    if 'error' in data:
                                        error_info = data['error']
                                        self.logger.error(
                                            f"❌ MediaStack API Error: {error_info.get('code')} - "
                                            f"{error_info.get('message')}"
                                        )
                                        continue
                                    
                                    articles = data.get('data', [])
                                    total = data.get('pagination', {}).get('total', 0)
                                    stats['total_fetched'] += len(articles)
                                    
                                    self.logger.info(
                                        f"📥 MediaStack [{language}]: Received {len(articles)}/{total} articles"
                                    )
                                    
                                    # Process and store articles
                                    for article_data in articles:
                                        if self.shutdown_flag:
                                            break
                                        result = await self.process_mediastack_article(article_data, language, session)
                                        if result == 'inserted':
                                            stats['inserted'] += 1
                                        elif result == 'skipped':
                                            stats['skipped'] += 1
                                        else:
                                            stats['errors'] += 1
                                
                                elif response.status == 429:
                                    self.logger.error(f"❌ MediaStack: Rate limit exceeded (429)")
                                    break  # Stop processing
                                elif response.status == 401:
                                    self.logger.error(f"❌ MediaStack: Invalid API key (401)")
                                    break
                                else:
                                    error_text = await response.text()
                                    self.logger.error(f"❌ MediaStack: HTTP {response.status} - {error_text[:200]}")
                        
                        except asyncio.TimeoutError:
                            self.logger.error(f"⏱️  MediaStack [{language}]: Timeout")
                            stats['errors'] += 1
                        except Exception as e:
                            self.logger.error(f"❌ MediaStack [{language}]: Error - {str(e)}")
                            stats['errors'] += 1
                        
                        # Rate limiting: Wait before next request (except after last one)
                        if not self.shutdown_flag and i < len(languages) - 1:
                            self.logger.debug(f"⏳ Waiting {MEDIASTACK_RATE_DELAY}s for rate limiting...")
                            await asyncio.sleep(MEDIASTACK_RATE_DELAY)
                
                # Log statistics
                self.logger.info(
                    f"✅ MediaStack cycle {cycle_count} complete: "
                    f"{stats['inserted']} inserted, {stats['skipped']} skipped, {stats['errors']} errors "
                    f"(fetched {stats['total_fetched']} total)"
                )
                
                if not self.shutdown_flag:
                    self.logger.info(f"MediaStack: Sleeping {MEDIASTACK_CYCLE_INTERVAL}s...")
                    await asyncio.sleep(MEDIASTACK_CYCLE_INTERVAL)
        except asyncio.CancelledError:
            self.logger.info("🌍 MediaStack collector cancelled")
        finally:
            self.logger.info("🌍 MediaStack collector stopped")
    
    async def process_mediastack_article(self, article_data, language, session):
        """
        Process and store a single MediaStack article.
        Returns: 'inserted', 'skipped', or 'error'
        """
        try:
            # Extract data with None handling
            title = article_data.get('title') or ''
            url = article_data.get('url') or ''
            description = article_data.get('description') or ''
            author = article_data.get('author') or ''
            source_name = article_data.get('source') or 'unknown'
            category = article_data.get('category') or 'general'
            published_at = article_data.get('published_at') or ''
            image = article_data.get('image') or ''
            
            # Strip and normalize whitespace
            title = ' '.join(title.split()) if title else ''
            url = url.strip() if url else ''
            description = description.strip() if description else ''
            author = author.strip() if author else ''
            source_name = source_name.strip() if source_name else 'unknown'
            category = category.strip() if category else 'general'
            
            # Validate required fields
            if not title or not url:
                return 'error'
            
            # Extract source URL from article URL
            source_url = ''
            try:
                parsed_url = urlparse(url)
                source_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            except:
                source_url = ''
            
            # Create normalized UTC version
            published_at_gmt = normalize_timestamp_to_utc(published_at)
            
            # Create source ID (mediastack-source_name)
            source_id = f"mediastack-{source_name.lower().replace(' ', '-').replace('_', '-')}"
            
            # Create article ID using original timestamp
            article_id = url_encode(title + url + published_at)
            
            # Ensure source exists
            is_new_source = await self.ensure_mediastack_source_exists(
                source_id, source_name, language, category, source_url
            )
            
            # Try to discover RSS feed for new sources
            if is_new_source and source_url:
                self.logger.debug(f"Attempting to discover RSS for MediaStack source: {source_name}...")
                self.loop.create_task(
                    self.register_rss_source(session, source_id, source_name, source_url)
                )
            
            # Create article object
            new_article = {
                'id_article': article_id,
                'id_source': source_id,
                'author': author[:200] if author else '',
                'title': title[:500] if title else '',
                'description': description[:1000] if description else '',
                'url': url[:500] if url else '',
                'urlToImage': image[:500] if image else '',
                'publishedAt': published_at,  # Original with timezone
                'published_at_gmt': published_at_gmt,  # Normalized UTC
                'content': ''
            }
            
            # Try to enrich with missing content from URL
            await self.enrich_article_content(new_article, source_name, source_id)
            
            # Insert article with lock
            async with self.db_lock:
                with self.eng.connect() as conn:
                    try:
                        ins = insert(self.gm_articles).values(**new_article)
                        ins_do_nothing = ins.on_conflict_do_nothing()
                        result = conn.execute(ins_do_nothing)
                        conn.commit()
                        
                        if result.rowcount > 0:
                            self.logger.debug(f"  ✅ MediaStack: {title[:60]}...")
                            return 'inserted'
                        else:
                            return 'skipped'
                    except Exception as e:
                        self.logger.error(f"Failed to insert MediaStack article: {e}")
                        conn.rollback()
                        return 'error'
        
        except Exception as e:
            self.logger.error(f"Error processing MediaStack article: {str(e)}")
            return 'error'
    
    async def ensure_mediastack_source_exists(self, source_id, source_name, language, category, source_url=''):
        """
        Ensure MediaStack source exists in database.
        Returns: True if source was newly created, False if it already existed
        """
        async with self.db_lock:
            with self.eng.connect() as conn:
                try:
                    # Check if source exists
                    stmt = select(self.gm_sources.c.id_source).where(
                        self.gm_sources.c.id_source == source_id
                    )
                    result = conn.execute(stmt).fetchone()
                    
                    if not result:
                        # Insert new source
                        ins = insert(self.gm_sources).values(
                            id_source=source_id,
                            name=source_name,
                            description='MediaStack news source',
                            url=source_url,  # Now capturing actual source URL
                            category=category,
                            language=language,
                            country=''
                        )
                        ins = ins.on_conflict_do_nothing(index_elements=['id_source'])
                        conn.execute(ins)
                        conn.commit()
                        self.logger.info(f"✅ Created MediaStack source: {source_name} ({source_url})")
                        return True
                    return False
                except Exception as e:
                    self.logger.error(f"Error ensuring MediaStack source exists: {e}")
                    conn.rollback()
                    return False
    
    async def enrich_article_content(self, article_dict, source_name='', source_id=''):
        """
        Attempt to fetch missing content from article URL.
        Updates article_dict in place with fetched data.
        Skips sources that are marked as blocked (403 errors).
        
        Args:
            article_dict: Dictionary with article data (must have 'url' key)
            source_name: Source name for logging
            source_id: Source ID for blocklist tracking
            
        Returns:
            bool: True if any content was fetched, False otherwise
        """
        # Check if enrichment is enabled
        if not ENRICH_MISSING_CONTENT:
            return False
        
        # Check if content is missing
        has_author = article_dict.get('author', '').strip()
        has_description = article_dict.get('description', '').strip()
        has_content = article_dict.get('content', '').strip()
        url = article_dict.get('url', '').strip()
        
        # If we already have everything, skip fetching
        if has_author and has_description and has_content:
            return False
        
        # If no URL, can't fetch
        if not url:
            return False
        
        # Check if this source is blocked (403s)
        if source_id:
            try:
                async with self.db_lock:
                    with self.eng.connect() as conn:
                        stmt = select(
                            self.gm_sources.c.fetch_blocked,
                            self.gm_sources.c.blocked_count
                        ).where(self.gm_sources.c.id_source == source_id)
                        result = conn.execute(stmt).fetchone()
                        
                        if result:
                            fetch_blocked, blocked_count = result
                            if fetch_blocked == 1:
                                self.logger.debug(f"⏭️  [{source_name}] Skipping fetch - source is blocklisted (403 count: {blocked_count})")
                                return False
            except Exception as e:
                self.logger.debug(f"Could not check blocklist for {source_name}: {e}")
        
        # Attempt to fetch content
        try:
            self.logger.debug(f"🔍 [{source_name}] Attempting to fetch missing content from URL...")
            
            # Run fetch in thread pool to avoid blocking async loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,  # Use default executor
                fetch_article_content,
                url,
                ENRICH_TIMEOUT
            )
            
            # Check for blocking error codes (401 Unauthorized, 402 Payment, 403 Forbidden, 406 Not Acceptable, 410 Gone, 500 Internal Error, 503 Unavailable, TIMEOUT)
            if result and result.get('error_code') in [401, 402, 403, 406, 410, 500, 503, 'TIMEOUT']:
                if source_id:
                    await self._increment_blocked_count(source_id, source_name, result.get('error_code'))
            
            if result and result.get('success'):
                updated = []
                
                # Update author if missing
                if not has_author and result.get('author'):
                    article_dict['author'] = result['author'][:200]
                    updated.append('author')
                
                # Update description if missing
                if not has_description and result.get('description'):
                    article_dict['description'] = result['description'][:1000]
                    updated.append('description')
                
                # Update content if missing
                if not has_content and result.get('content'):
                    article_dict['content'] = result['content'][:2000]  # Store first 2000 chars
                    updated.append('content')
                
                # Update published time if missing and fetched
                if not article_dict.get('publishedAt') and result.get('published_time'):
                    article_dict['publishedAt'] = result['published_time']
                    updated.append('publishedAt')
                
                if updated:
                    self.logger.debug(f"✅ [{source_name}] Enriched article with: {', '.join(updated)}")
                    return True
                else:
                    self.logger.debug(f"⚠️  [{source_name}] Fetch succeeded but no new data found")
                    return False
            else:
                self.logger.debug(f"⚠️  [{source_name}] Content fetch failed or returned no data")
                return False
                
        except Exception as e:
            error_msg = str(e)
            # Check if it's a blocking error (402 Payment Required, 403 Forbidden, 406 Not Acceptable, 410 Gone)
            if any(code in error_msg for code in ['402', 'Payment Required', '403', 'Forbidden', '406', 'Not Acceptable', '410', 'Gone']):
                if source_id:
                    # Try to extract actual error code from message
                    error_code = 403  # default
                    if '402' in error_msg or 'Payment Required' in error_msg:
                        error_code = 402
                    elif '406' in error_msg or 'Not Acceptable' in error_msg:
                        error_code = 406
                    elif '410' in error_msg or 'Gone' in error_msg:
                        error_code = 410
                    await self._increment_blocked_count(source_id, source_name, error_code)
            self.logger.warning(f"⚠️  [{source_name}] Error fetching content: {e}")
            return False
    
    async def _increment_blocked_count(self, source_id, source_name='', error_code=403):
        """
        Increment the blocked_count for a source and mark as blocked if threshold reached.
        Threshold: 3 consecutive errors (401/402/403/406/410/500/503/TIMEOUT) marks source as blocked.
        
        Args:
            source_id: Source identifier
            source_name: Source name for logging
            error_code: HTTP error code or 'TIMEOUT' (401 Unauthorized, 402 Payment, 403 Forbidden, 406 Not Acceptable, 410 Gone, 500 Internal Error, 503 Unavailable, TIMEOUT, etc.)
        """
        try:
            async with self.db_lock:
                with self.eng.connect() as conn:
                    # Get current count
                    stmt = select(
                        self.gm_sources.c.blocked_count,
                        self.gm_sources.c.fetch_blocked
                    ).where(self.gm_sources.c.id_source == source_id)
                    result = conn.execute(stmt).fetchone()
                    
                    if result:
                        current_count, currently_blocked = result
                        new_count = current_count + 1
                        
                        # Mark as blocked if 3+ HTTP errors
                        should_block = 1 if new_count >= 3 else 0
                        
                        # Update the source
                        update_stmt = self.gm_sources.update().where(
                            self.gm_sources.c.id_source == source_id
                        ).values(
                            blocked_count=new_count,
                            fetch_blocked=should_block
                        )
                        conn.execute(update_stmt)
                        conn.commit()
                        
                        if should_block == 1 and currently_blocked == 0:
                            self.logger.warning(f"🚫 [{source_name}] Blocklisted after {new_count} HTTP {error_code} errors - will skip future fetches")
                        else:
                            self.logger.debug(f"⚠️  [{source_name}] HTTP {error_code} error #{new_count}")
        except Exception as e:
            self.logger.debug(f"Could not update blocked_count for {source_name}: {e}")
                     
    def getNewsSources(self):
#        url = "https://newsapi.org/v2/sources?country=br&apiKey=" + API_KEY
        url = "https://newsapi.org/v2/sources?language=en&apiKey=" + API_KEY1
        print('getNewsSource url:',url)
        sources = []

        req = urllib.request.Request(url, headers=self._build_http_headers(url))
        with urllib.request.urlopen(req) as response:
            response_text = response.read()   
            encoding = response.info().get_content_charset('utf-8')
            JSON_object = json.loads(response_text.decode(encoding))                        
            #return JSON_object            
            for source in JSON_object["sources"]:
                print(source)
                source_key          = source['id']
                source_name         = source['name']
                source_url          = source['url']
                source_description  = source['description']
                source['articles'] = dict()
#                self.sources_list.InsertItem(0, source_name)
                sources.append(source)
        return sources


if __name__ == '__main__':
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)
    
    # Create event loop
    loop = asyncio.get_event_loop()
    app = NewsGather(loop)
    
    # Track collector tasks for graceful cancellation
    collector_tasks = []
    
    # Setup async signal handler for graceful shutdown
    def handle_shutdown_signal():
        """Handle shutdown signals by cancelling all collector tasks"""
        app.logger.info("\n🛑 Received shutdown signal. Cancelling collectors...")
        app.shutdown_flag = True
        
        # Cancel all collector tasks
        for task in collector_tasks:
            if not task.done():
                task.cancel()
        
        app.logger.info("✅ Shutdown signal processed")
    
    # Register signal handlers (asyncio-compatible)
    loop.add_signal_handler(signal.SIGINT, handle_shutdown_signal)   # Ctrl+C
    loop.add_signal_handler(signal.SIGTERM, handle_shutdown_signal)  # systemd stop
    
    # Run all three collectors in parallel
    async def run_all_collectors():
        app.logger.info("🚀 Starting all news collectors in parallel...")
        app.logger.info(f"   • NewsAPI: every {NEWSAPI_CYCLE_INTERVAL}s ({NEWSAPI_CYCLE_INTERVAL//60} min)")
        app.logger.info(f"   • RSS Feeds: every {RSS_CYCLE_INTERVAL}s ({RSS_CYCLE_INTERVAL//60} min)")
        app.logger.info(f"   • MediaStack: every {MEDIASTACK_CYCLE_INTERVAL}s ({MEDIASTACK_CYCLE_INTERVAL//60} min)")
        
        # Create tasks for all collectors
        tasks = [
            loop.create_task(app.collect_newsapi()),
            loop.create_task(app.collect_rss_feeds()),
            loop.create_task(app.collect_mediastack())
        ]
        
        # Store tasks globally for signal handler access
        collector_tasks.extend(tasks)
        
        try:
            # Wait for all tasks to complete (or be cancelled)
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            app.logger.info("🏁 Collectors cancelled")
        except Exception as e:
            app.logger.error(f"Error in collectors: {e}", exc_info=True)
        finally:
            # Cancel any remaining tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            
            # Wait for all tasks to finish cancellation
            await asyncio.gather(*tasks, return_exceptions=True)
            app.logger.info("🏁 All collectors stopped")
    
    try:
        loop.run_until_complete(run_all_collectors())
    except KeyboardInterrupt:
        app.logger.info("🛑 Interrupted by user")
    finally:
        # Close database and cleanup resources
        app.shutdown()
        
        # Clean up pending tasks
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        
        # Wait for all tasks to complete cancellation
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        
        loop.close()
        app.logger.info("👋 wxAsyncNewsGather shutdown complete")
