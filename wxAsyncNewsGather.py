#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec  2 16:21:25 2019

@author: jamaj
"""

from __future__ import print_function

import logging
import logging.handlers
import sys
from multiprocessing import Queue
import re
import subprocess
import tempfile
from typing import Any, Optional, Tuple

import urllib.request 
import json
import webbrowser

import asyncio, aiohttp
import aiosqlite

from asyncio.events import get_event_loop
import time
import base64
import zlib

from sqlalchemy import (create_engine, Table, Column, Integer, 
    String, MetaData, Text)
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.sqlite import insert
import hashlib
import os
from urllib.parse import urlparse
import feedparser
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateutil_parser
import pytz

# Load credentials from environment
from decouple import config

# Import article content fetcher
from article_fetcher import fetch_article_content, fetch_article_content_async, ERROR_PERMANENT
import signal

# Shared HTML utilities (also used by enrichment_worker)
from html_utils import (
    HTMLContentSanitizer,
    fix_encoding_if_needed,
    sanitize_html_content,
    extract_first_image_url,
    extract_and_remove_first_image,
)

# Async parallel enrichment worker
from enrichment_worker import EnrichmentWorker, _BLOCKED_THRESHOLD

# Centralised async CRUD layer (backed by aiosqlite)
from news_db import NewsDatabase

# FastAPI server (optional - enabled via API_SERVER_ENABLED)
try:
    from fastapi import FastAPI, Query, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from sqlalchemy import func
    import uvicorn
    _FASTAPI_AVAILABLE = True
except ImportError:
    FastAPI = None  # type: ignore[assignment,misc]
    Query = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    CORSMiddleware = None  # type: ignore[assignment,misc]
    JSONResponse = None  # type: ignore[assignment,misc]
    uvicorn = None  # type: ignore[assignment]
    _FASTAPI_AVAILABLE = False
    logging.warning("⚠️  fastapi/uvicorn not available - API server disabled. Install with: pip install fastapi uvicorn")

# Language detection
try:
    from langdetect import detect, detect_langs, LangDetectException  # type: ignore
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    detect = None  # type: ignore
    detect_langs = None  # type: ignore
    LangDetectException = Exception  # type: ignore
    logging.warning("⚠️  langdetect not available - language detection disabled. Install with: pip install langdetect")

# Languages that are unlikely to appear in news feeds but that langdetect
# commonly produces as false positives for short English/Latin-script text.
_LANGDETECT_LOW_PRIOR_LANGS = frozenset({
    'cy',   # Welsh — frequent false positive for English headlines
    'mt',   # Maltese
    'la',   # Latin
    'af',   # Afrikaans (often confused with English/Dutch)
    'so',   # Somali false-positive on some English patterns
})
# Minimum probability required to trust a low-prior language detection.
# Below this threshold the runner-up language (if any) is used instead.
_LOW_PRIOR_MIN_PROB = 0.90

# NewsAPI Configuration
API_KEY1 = str(config('NEWS_API_KEY_1', cast=str))
API_KEY2 = str(config('NEWS_API_KEY_2', cast=str))
NEWSAPI_CYCLE_INTERVAL = int(config('NEWSAPI_CYCLE_INTERVAL', default=600))  # 10 minutes

# RSS Configuration
RSS_TIMEOUT = int(config('RSS_TIMEOUT', default=15))
RSS_MAX_CONCURRENT = int(config('RSS_MAX_CONCURRENT', default=20))
RSS_BATCH_SIZE = int(config('RSS_BATCH_SIZE', default=20))
RSS_CYCLE_INTERVAL = int(config('RSS_CYCLE_INTERVAL', default=900))  # 15 minutes

# MediaStack Configuration
MEDIASTACK_API_KEY = str(config('MEDIASTACK_API_KEY', cast=str))
MEDIASTACK_API_KEY_2 = str(config('MEDIASTACK_API_KEY_2', default='', cast=str))
MEDIASTACK_API_KEY_3 = str(config('MEDIASTACK_API_KEY_3', default='', cast=str))
MEDIASTACK_API_KEY_4 = str(config('MEDIASTACK_API_KEY_4', default='', cast=str))
MEDIASTACK_API_KEYS = [k for k in [MEDIASTACK_API_KEY, MEDIASTACK_API_KEY_2, MEDIASTACK_API_KEY_3, MEDIASTACK_API_KEY_4] if k]
MEDIASTACK_BASE_URL = str(config(
    'MEDIASTACK_BASE_URL',
    default='https://api.mediastack.com/v1/news',
    cast=str,
))
MEDIASTACK_RATE_DELAY = 20  # Delay between requests (seconds) - 3 requests/minute
MEDIASTACK_CYCLE_INTERVAL = int(config('MEDIASTACK_CYCLE_INTERVAL', default=21600))  # 6 hours — safe for 100 req/month/key with 4 keys rotating (90 req/key/month)

# Content Enrichment Configuration
ENRICH_MISSING_CONTENT = config('ENRICH_MISSING_CONTENT', default=True, cast=bool)
ENRICH_TIMEOUT = int(config('ENRICH_TIMEOUT', default=10))
ENRICH_CONCURRENCY = int(config('ENRICH_CONCURRENCY', default=32))

# Per-tier enrichment tuning (tiered pipeline: cffi → requests → playwright)
CFFI_CONCURRENCY    = int(config('CFFI_CONCURRENCY',    default=40))
CFFI_TIMEOUT        = int(config('CFFI_TIMEOUT',        default=12))
CFFI_BATCH_SIZE     = int(config('CFFI_BATCH_SIZE',     default=80))
REQUESTS_CONCURRENCY = int(config('REQUESTS_CONCURRENCY', default=20))
REQUESTS_TIMEOUT     = int(config('REQUESTS_TIMEOUT',     default=15))
REQUESTS_BATCH_SIZE  = int(config('REQUESTS_BATCH_SIZE',  default=40))
PLAYWRIGHT_CONCURRENCY = int(config('PLAYWRIGHT_CONCURRENCY', default=6))
PLAYWRIGHT_TIMEOUT     = int(config('PLAYWRIGHT_TIMEOUT',     default=30))
PLAYWRIGHT_BATCH_SIZE  = int(config('PLAYWRIGHT_BATCH_SIZE',  default=12))

# API Server Configuration
API_SERVER_ENABLED = config('API_SERVER_ENABLED', default=True, cast=bool)
API_PORT = int(config('NEWS_API_PORT', default=8765))
API_HOST = str(config('NEWS_API_HOST', default='0.0.0.0'))
API_MAX_ARTICLES = 200

# Backfill Configuration — enriches existing articles that have no content yet
BACKFILL_ENABLED = config('BACKFILL_ENABLED', default=True, cast=bool)
BACKFILL_BATCH_SIZE = int(config('BACKFILL_BATCH_SIZE', default=50))   # articles per batch
BACKFILL_DELAY = float(config('BACKFILL_DELAY', default=1.0))           # seconds between articles
BACKFILL_CYCLE_INTERVAL = int(config('BACKFILL_CYCLE_INTERVAL', default=10))  # seconds between cycles

TRANSLATE_ENABLED = config('TRANSLATE_ENABLED', default=True, cast=bool)
TRANSLATE_BATCH_SIZE = int(config('TRANSLATE_BATCH_SIZE', default=100))     # articles per batch
TRANSLATE_DELAY = float(config('TRANSLATE_DELAY', default=2.0))             # seconds between articles
TRANSLATE_CYCLE_INTERVAL = int(config('TRANSLATE_CYCLE_INTERVAL', default=60))    # 60s between cycles

# Blocked-source probing — periodically re-tests blocked sources and unblocks survivors
PROBE_ENABLED = config('PROBE_ENABLED', default=True, cast=bool)
PROBE_CYCLE_INTERVAL = int(config('PROBE_CYCLE_INTERVAL', default=3600))  # 1 hour between full cycles
PROBE_DELAY = float(config('PROBE_DELAY', default=2.0))                   # seconds between individual probes
PROBE_TIMEOUT = int(config('PROBE_TIMEOUT', default=15))                  # fetch timeout per probe

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


def url_encode(url: str) -> bytes:
    return base64.urlsafe_b64encode(zlib.compress(url.encode('utf-8')))[15:31]


# HTML utilities are imported from html_utils (see top of file)
import html
from html.parser import HTMLParser


def dbCredentials() -> str:
    """Return SQLite database path"""
    db_path = str(config('DB_PATH', default='predator_news.db', cast=str))
    # Make path absolute if relative
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path


def as_text(value: Any) -> str:
    """Return a safe string for loosely-typed feed/API fields with encoding fix."""
    if value is None:
        return ""
    if isinstance(value, str):
        # Fix encoding issues before returning
        return fix_encoding_if_needed(value)
    if isinstance(value, list):
        return " ".join(as_text(item) for item in value if item is not None)
    result = str(value)
    return fix_encoding_if_needed(result)


def _make_title_hash(title: str) -> str:
    """SHA-1 of lowercased, stripped title — used for cross-feed dedup."""
    if not title:
        return ''
    norm = ' '.join(title.lower().split())
    return hashlib.sha1(norm.encode('utf-8', errors='ignore')).hexdigest()[:16]


def detect_article_language(
    title: Optional[str],
    description: Optional[str] = None,
    content: Optional[str] = None,
) -> tuple[Optional[str], float]:
    """
    Detect language of article using langdetect
    
    Args:
        title: Article title
        description: Article description (optional)
        content: Article content (optional)
    
    Returns:
        tuple: (language_code, confidence) or (None, 0.0) if detection fails
    """
    if not LANGDETECT_AVAILABLE:
        return None, 0.0
    
    # Assertion for type checker - at this point, detect and LangDetectException are available
    assert detect is not None, "detect should be available when LANGDETECT_AVAILABLE is True"
    assert detect_langs is not None, "detect_langs should be available when LANGDETECT_AVAILABLE is True"

    # Build detection text (prefer longer text for better accuracy)
    detection_text = ""

    if content and len(content.strip()) > 100:
        detection_text = content[:500]  # Use first 500 chars of content
    elif description and len(description.strip()) > 50:
        detection_text = description[:300]  # Use description
    elif title:
        detection_text = title  # Fallback to title
    else:
        return None, 0.0

    # Clean HTML tags if present
    detection_text = re.sub(r'<[^>]+>', '', detection_text).strip()

    if len(detection_text) < 10:
        return None, 0.0

    try:
        probs = detect_langs(detection_text)  # list of Language(lang, prob), sorted desc
        if not probs:
            return None, 0.0
        top = probs[0]
        lang_code, confidence = top.lang, top.prob

        # langdetect frequently mis-classifies short English/Latin-script news
        # headlines as Welsh (cy) and a few other rare languages.  If the top
        # result is one of those low-prior languages and its probability is
        # below the threshold, fall back to the next candidate (if any) so we
        # don't waste translation resources on a phantom Welsh article.
        if lang_code in _LANGDETECT_LOW_PRIOR_LANGS and confidence < _LOW_PRIOR_MIN_PROB:
            if len(probs) > 1:
                lang_code, confidence = probs[1].lang, probs[1].prob
            else:
                return None, 0.0

        return lang_code, round(confidence, 4)
    except (LangDetectException, Exception):
        # Detection failed (text too short, unknown language, etc.)
        return None, 0.0


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


def normalize_timestamp_to_utc(
    timestamp_str: str,
    source_timezone: Optional[str] = None,
    use_source_timezone: bool = False,
) -> tuple[Optional[str], Optional[str]]:
    """
    Normalize a timestamp string to UTC (GMT+0).
    
    SMART TIMEZONE CORRECTION LOGIC:
    1. Parse article timestamp with its timezone (if present)
    2. If use_source_timezone=True and source_timezone is provided:
       a. Convert timestamp to UTC using article's timezone (or UTC if none)
       b. Compare with current UTC time
       c. If timestamp is >30 minutes in the future → Apply source_timezone correction
       d. Otherwise → Use article's timezone (it's correct)
    3. If article has no timezone → Use source_timezone (if available)
    4. Return None if no timezone info available
    
    This prevents overcorrection of sources that sometimes report correct timezones,
    while still fixing sources that consistently lie about their timezone.
    
    Args:
        timestamp_str: Timestamp string with timezone info (ISO, RFC 2822, etc.)
        source_timezone: Optional timezone offset string (e.g., 'UTC+05:30')
        use_source_timezone: If True, apply source_timezone only when timestamp is in future
    
    Returns:
        Tuple: (utc_timestamp_str, detected_timezone_str)
        - utc_timestamp_str: ISO format UTC timestamp, or None if no timezone available
        - detected_timezone_str: Detected timezone offset (e.g., 'UTC+05:30') or None
    """
    if not timestamp_str or timestamp_str.strip() == '':
        return datetime.now(timezone.utc).isoformat(), None
    
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
    
    # Pre-process: Fix truncated timezone offsets (3 digits instead of 4)
    # Some RSS feeds send +000, +010, +053 instead of +0000, +0100, +0530
    # Example: "Sun, 01 Mar 2026 22:44:21 +000" → "Sun, 01 Mar 2026 22:44:21 +0000"
    import re
    truncated_tz_pattern = r'([+-])(\d)(\d)(\d)(?!\d)'  # Match +NNN or -NNN (3 digits, not followed by another digit)
    match = re.search(truncated_tz_pattern, timestamp_str)
    if match:
        # Expand truncated timezone: +010 → +0100, +053 → +0530
        sign = match.group(1)
        digit1 = match.group(2)
        digit2 = match.group(3)
        digit3 = match.group(4)
        
        # Reconstruct as HHMM format
        expanded_tz = f"{sign}{digit1}{digit2}{digit3}0"
        timestamp_str = timestamp_str[:match.start()] + expanded_tz + timestamp_str[match.end():]

    # Pre-process: Replace IANA timezone names (e.g. "Europe/Dublin") with their
    # UTC offset so dateutil can parse them.  Some RSS feeds (e.g. breakingnews.ie)
    # embed the full zone name instead of a numeric offset.
    iana_tz_pattern = re.compile(r'([A-Za-z]+/[A-Za-z_]+)')
    iana_match = iana_tz_pattern.search(timestamp_str)
    if iana_match:
        try:
            tz_obj = pytz.timezone(iana_match.group(1))
            # Use the current UTC offset for this zone (accounts for DST)
            now_offset = datetime.now(tz_obj).utcoffset()
            total_secs = int(now_offset.total_seconds())
            h, rem = divmod(abs(total_secs), 3600)
            m = rem // 60
            offset_str = f"{'+' if total_secs >= 0 else '-'}{h:02d}{m:02d}"
            timestamp_str = timestamp_str[:iana_match.start()] + offset_str + timestamp_str[iana_match.end():]
        except Exception:
            # Unknown IANA zone — strip it so dateutil at least parses the date
            timestamp_str = timestamp_str[:iana_match.start()].rstrip()

    try:
        # Parse the timestamp with dateutil (handles most formats and extracts timezone)
        parsed_dt = dateutil_parser.parse(timestamp_str, tzinfos=tzinfos)
        detected_tz = None
        
        # SMART TIMEZONE CORRECTION LOGIC (changed behavior)
        # If use_source_timezone=True, we have a confirmed source timezone,
        # but we should only apply it if the article timestamp is in the future.
        # This prevents overcorrection of sources that sometimes report correct timezones.
        if use_source_timezone and source_timezone:
            from dateutil.tz import tzoffset
            import re
            
            # First, try to convert with article's timezone (if present)
            test_dt = parsed_dt
            if parsed_dt.tzinfo is None:
                # No timezone in article - try UTC first
                test_dt = parsed_dt.replace(tzinfo=timezone.utc)
            
            # Convert to UTC for comparison
            test_utc = test_dt.astimezone(timezone.utc)
            now_utc = datetime.now(timezone.utc)
            
            # Check if timestamp is in the future (more than 30 minutes ahead)
            time_diff_minutes = (test_utc - now_utc).total_seconds() / 60
            
            if time_diff_minutes > 30:
                # Timestamp is in the future - article timezone is WRONG
                # The feed incorrectly added source timezone offset to the timestamp
                # We need to UNDO that addition by subtracting the offset
                tz_match = re.search(r'([+-])?(\d{2}):(\d{2})', source_timezone)
                if tz_match:
                    # Parse source timezone offset
                    # CRITICAL: For UTC-03:00, we want to SUBTRACT 3h (so sign should be +1)
                    # For UTC+05:00, we want to ADD 5h (so sign should be -1, subtract negative = add)
                    sign = 1 if tz_match.group(1) == '-' else -1  # INVERTED on purpose!
                    hours = int(tz_match.group(2))
                    minutes = int(tz_match.group(3))
                    total_seconds = sign * (hours * 3600 + minutes * 60)
                    
                    # Log correction for debugging
                    logging.debug(f"TIMEZONE-CORRECTION: Article timestamp is {time_diff_minutes:.1f}min in future, subtracting {total_seconds/3600:.1f}h to correct")
                    
                    # CRITICAL FIX: Subtract the offset from timestamp
                    # Example: Feed reports "04:43:09 +0000" but it's Argentina (UTC-03:00)
                    # The feed ADDED 3h incorrectly, so we SUBTRACT 3h: 04:43 - 3h = 01:43 UTC ✓
                    # Strip any existing timezone and treat as naive
                    parsed_dt = parsed_dt.replace(tzinfo=None)
                    
                    # Subtract the source timezone offset
                    corrected_dt = parsed_dt - timedelta(seconds=total_seconds)
                    
                    # Now mark as UTC
                    utc_dt = corrected_dt.replace(tzinfo=timezone.utc)
                    detected_tz = source_timezone
                    
                    return utc_dt.replace(microsecond=0).isoformat(), detected_tz
            
            # If we reach here: timestamp is NOT in the future
            # Continue with normal processing (use article timezone)
        
        # PRIORITY 1: Check if article timestamp has timezone info
        if parsed_dt.tzinfo is not None:
            # Article has timezone - USE IT (only if use_source_timezone is False)
            # Extract detected timezone as UTC offset string
            offset = parsed_dt.utcoffset()
            if offset is not None:  # Changed from 'if offset:' to handle UTC+00:00 correctly
                total_seconds = int(offset.total_seconds())
                hours, remainder = divmod(abs(total_seconds), 3600)
                minutes = remainder // 60
                sign = '+' if total_seconds >= 0 else '-'
                detected_tz = f"UTC{sign}{hours:02d}:{minutes:02d}"
        else:
            # No timezone in article timestamp
            # PRIORITY 2: Check if timestamp text claims to be GMT/UTC
            if 'GMT' in timestamp_str.upper() or 'UTC' in timestamp_str.upper():
                # Timestamp claims to be GMT/UTC, treat as such
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                detected_tz = 'UTC+00:00'
            # PRIORITY 3: Use source timezone if permitted
            elif use_source_timezone and source_timezone:
                # Source timezone can be used (confirmed source)
                from dateutil.tz import tzoffset
                import re
                
                # Parse timezone offset from string like 'UTC+05:30'
                tz_match = re.search(r'([+-])?(\d{2}):(\d{2})', source_timezone)
                if tz_match:
                    sign = -1 if tz_match.group(1) == '-' else 1
                    hours = int(tz_match.group(2))
                    minutes = int(tz_match.group(3))
                    total_seconds = sign * (hours * 3600 + minutes * 60)
                    tz_offset = tzoffset('', total_seconds)
                    parsed_dt = parsed_dt.replace(tzinfo=tz_offset)
                    detected_tz = source_timezone
                else:
                    # Invalid source timezone format
                    return None, None
            else:
                # PRIORITY 4: No timezone available - CANNOT CONVERT
                return None, None
        
        # Convert to UTC
        utc_dt = parsed_dt.astimezone(timezone.utc)
        
        # Return ISO format without microseconds for consistency, plus detected timezone
        return utc_dt.replace(microsecond=0).isoformat(), detected_tz
        
    except Exception as e:
        # If parsing fails, return current UTC time
        logging.debug(f"Failed to parse timestamp '{timestamp_str}': {e}")
        return datetime.now(timezone.utc).isoformat(), None


def detect_timezone_from_articles(
    articles_timestamps: list[str],
    source_name: str = "Unknown",
    logger: Optional[logging.Logger] = None,
) -> tuple[Optional[str], bool]:
    """
    Analisa todos os timestamps de artigos para detectar se o fuso está incorreto.
    
    Estratégia:
    1. Converte todos os timestamps para GMT usando o fuso que eles reportam
    2. Compara cada um com o horário atual do servidor
    3. Se a maioria está no futuro com offset similar, calcula o fuso correto
    4. Retorna o fuso detectado ou None se tudo estiver correto
    
    Args:
        articles_timestamps: Lista de timestamps strings dos artigos
        source_name: Nome da fonte (para logging)
        logger: Logger para mensagens
    
    Returns:
        Tuple: (corrected_timezone, should_enable_use_timezone)
        - corrected_timezone: String com fuso correto (e.g., 'UTC-03:00') ou None
        - should_enable_use_timezone: True se deve ativar use_timezone=1
    """
    if not articles_timestamps or len(articles_timestamps) == 0:
        return None, False
    
    if logger is None:
        logger = logging.getLogger(__name__)
    
    now_utc = datetime.now(timezone.utc)
    future_offsets = []  # Offsets em segundos de artigos no futuro
    
    # Analisa cada timestamp
    for ts_str in articles_timestamps:
        if not ts_str:
            continue
            
        try:
            # Converte para GMT usando o fuso que o artigo reporta (ou UTC se não reportar)
            gmt_timestamp, detected_tz = normalize_timestamp_to_utc(ts_str, source_timezone=None, use_source_timezone=False)
            
            if not gmt_timestamp:
                continue
            
            # Parse o GMT timestamp
            parsed_gmt = datetime.fromisoformat(gmt_timestamp.replace('Z', '+00:00'))
            
            # Calcula diferença com horário atual
            time_diff = (parsed_gmt - now_utc).total_seconds()
            
            # Se está no futuro (considerando pequena margem de 2 minutos para latência de rede)
            if time_diff > 120:  # 2 minutos
                future_offsets.append(time_diff)
                
        except Exception as e:
            logger.debug(f"Failed to analyze timestamp '{ts_str}': {e}")
            continue
    
    # Verifica se há padrão consistente de artigos no futuro
    if len(future_offsets) == 0:
        # Nenhum artigo no futuro - tudo correto
        return None, False
    
    # Calcula offset médio e verifica consistência
    avg_offset = sum(future_offsets) / len(future_offsets)
    
    # Calcula desvio padrão para verificar consistência
    variance = sum((x - avg_offset) ** 2 for x in future_offsets) / len(future_offsets)
    std_dev = variance ** 0.5
    
    # Se pelo menos 50% dos artigos estão no futuro E o desvio é pequeno (offset consistente)
    consistency_ratio = len(future_offsets) / len(articles_timestamps)
    
    if consistency_ratio >= 0.5 and std_dev < 3600:  # Desvio < 1 hora
        # Detectado padrão consistente - calcular fuso correto
        hours_offset = int(avg_offset) // 3600
        minutes_offset = (int(avg_offset) % 3600) // 60
        
        # Arredondar para incremento de 30 minutos (fusos comuns)
        if minutes_offset > 15 and minutes_offset < 45:
            minutes_offset = 30
        elif minutes_offset >= 45:
            hours_offset += 1
            minutes_offset = 0
        else:
            minutes_offset = 0
        
        # Formato: UTC-HH:MM (negativo porque o feed reporta tempo local como UTC)
        corrected_tz = f"UTC-{abs(hours_offset):02d}:{minutes_offset:02d}"
        
        logger.warning(
            f"🔍 TIMEZONE-DETECTION: [{source_name}] {len(future_offsets)}/{len(articles_timestamps)} "
            f"artigos estão {hours_offset}h{minutes_offset}m no futuro (consistência: {consistency_ratio*100:.1f}%). "
            f"Feed reporta UTC mas publica hora local. Fuso correto: {corrected_tz}"
        )
        
        return corrected_tz, True
    
    # Padrão inconsistente - pode ser problema diferente
    logger.debug(
        f"⚠️  [{source_name}] {len(future_offsets)}/{len(articles_timestamps)} artigos no futuro, "
        f"mas offset inconsistente (std_dev={std_dev/3600:.2f}h). Não corrigindo automaticamente."
    )
    
    return None, False


class NewsGather():
    def __init__(self, loop):
        self.logger = logging.getLogger(__name__)
        self.sources = dict()
        self.loop = loop
        self.shutdown_flag = False  # Flag para shutdown gracioso
        
        # API key rotation for NewsAPI
        self.newsapi_keys = [API_KEY1, API_KEY2]
        self.current_newsapi_key_index = 0

        # API key rotation for MediaStack
        self.current_mediastack_key_index = 0
   
        self.logger.info("Initializing NewsGather...")
        self.logger.debug("Creating URL queue")
        self.url_queue = Queue()   
       
        self.logger.info("Opening database connection")
        self.eng = self.dbOpen()
        self.meta = MetaData()        
        self.gm_sources = Table('gm_sources', self.meta, autoload_with=self.eng) 
        self.gm_articles = Table('gm_articles', self.meta, autoload_with=self.eng) 
        
        # Sources and blocked domains are loaded asynchronously in open_async_db().
        self.sources = dict()

        # Centralised async CRUD layer; opened in open_async_db() at startup.
        self.db: Optional[NewsDatabase] = None

        # Tiered parallel enrichment workers (cffi → requests → playwright)
        self._cffi_worker = EnrichmentWorker(
            concurrency=CFFI_CONCURRENCY,
            timeout=CFFI_TIMEOUT,
            backend='cffi',
        )
        self._requests_worker = EnrichmentWorker(
            concurrency=REQUESTS_CONCURRENCY,
            timeout=REQUESTS_TIMEOUT,
            backend='requests',
        )
        self._playwright_worker = EnrichmentWorker(
            concurrency=PLAYWRIGHT_CONCURRENCY,
            timeout=PLAYWRIGHT_TIMEOUT,
            backend='playwright',
        )
        # Legacy single-worker alias (used by enrich_article_content helper)
        self._enrichment_worker = self._cffi_worker

        # Set of article IDs currently in the enrichment pipeline; updated by
        # backfill_content() and exposed via GET /api/queues.
        self._backfill_processing_ids: set[int] = set()
    
    async def open_async_db(self) -> None:
        """
        Open the aiosqlite connection and finish async initialisation.
        Called once at the very start of run_all_collectors() before any
        collector tasks are created.
        """
        self.db = await NewsDatabase.open(self.db_path)

        # Load sources into memory
        source_rows = await self.db.load_sources()
        self.sources = {
            r['id_source']: {
                'id_source':    r['id_source'],
                'name':         r.get('name',        ''),
                'description':  r.get('description', ''),
                'url':          r.get('url',         ''),
                'category':     r.get('category',    ''),
                'language':     r.get('language',    ''),
                'country':      r.get('country',     ''),
                'timezone':     r.get('timezone'),
                'use_timezone': r.get('use_timezone', 0),
                'articles':     {},
            }
            for r in source_rows
        }
        self.logger.info(f"🗄️  Loaded {len(self.sources)} sources via aiosqlite")

        # Pre-populate blocked domains into the enrichment worker so domains
        # that were already blocked survive a service restart.
        try:
            blocked = await self.db.load_blocked_domains()
            for (domain, cnt) in blocked:
                self._enrichment_worker._error_counts[domain] = max(cnt, _BLOCKED_THRESHOLD)
            if blocked:
                self.logger.info(f"🔒 Loaded {len(blocked)} blocked domain(s) into enrichment worker")
        except Exception:
            pass  # Table may not exist yet on first run

    def shutdown(self):
        """
        Gracefully shutdown the application.
        Note: shutdown_flag should already be set before calling this.
        The aiosqlite connection is closed inside run_all_collectors() finally.
        """
        self.logger.info("🛑 Shutting down NewsGather...")
        try:
            if hasattr(self, 'eng') and self.eng:
                self.eng.dispose()
                self.logger.info("✅ SQLAlchemy engine disposed")
        except Exception as e:
            self.logger.error(f"Error disposing engine: {e}")
        self.logger.info("✅ Shutdown complete")

    def _build_http_headers(self, url: str) -> dict:
        headers = dict(BASIC_HTTP_HEADERS)
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            # NDTV Profit requires specific User-Agent to allow RSS access
            if parsed.netloc.endswith("ndtvprofit.com"):
                headers["User-Agent"] = "FeedReader/1.0 (Linux)"
                headers["Referer"] = "https://www.ndtvprofit.com/"
            # OneIndia requires Googlebot User-Agent (blocks regular browsers with 403)
            elif parsed.netloc.endswith("oneindia.com"):
                headers["User-Agent"] = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
                headers["Referer"] = "https://www.oneindia.com/"
            elif parsed.netloc.endswith("indianexpress.com"):
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

    def _looks_like_feed_body(self, content) -> bool:
        """Check if content (bytes or str) looks like RSS/XML feed"""
        if isinstance(content, bytes):
            sample = content[:2000].lower()
            return any(tag in sample for tag in (b"<?xml", b"<rss", b"<feed", b"<rdf:rdf"))
        sample = (content or "")[:2000].lower()
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
            
            # Return raw bytes - let feedparser handle encoding
            return status, content_type, body_bytes
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
            # Get raw bytes - let feedparser handle encoding detection
            content = await response.read()

        if status == 403:
            try:
                status, content_type, content = await asyncio.to_thread(
                    self._fetch_rss_with_curl, rss_url, timeout_seconds
                )
            except Exception as exc:
                self.logger.debug(f"Curl fallback failed for {rss_url}: {exc}")
        return status, content_type, content
    
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
                        'timezone': source[9] if len(source) > 9 else None,  # Timezone offset (UTC+XX:XX)
                        'use_timezone': source[10] if len(source) > 10 else 0,  # Whether to apply source timezone
                        'articles': {}  # Empty dict - articles checked via SQLite, not memory
                     }

            self.logger.info(f"InitArticles: Loaded {source_count} sources (articles managed by SQLite)")
        return sources

    async def reload_sources(self):
        """
        Reload sources from database.
        Called at the end of each collection cycle to pick up any changes
        (new sources added, sources blocked, URLs updated, etc.)
        """
        try:
            rows = await self.db.load_sources()
            new_sources = {
                r['id_source']: {
                    'id_source':    r['id_source'],
                    'name':         r.get('name',        ''),
                    'description':  r.get('description', ''),
                    'url':          r.get('url',         ''),
                    'category':     r.get('category',    ''),
                    'language':     r.get('language',    ''),
                    'country':      r.get('country',     ''),
                    'timezone':     r.get('timezone'),
                    'use_timezone': r.get('use_timezone', 0),
                    'articles':     {},
                }
                for r in rows
            }
            added   = len(set(new_sources) - set(self.sources))
            removed = len(set(self.sources) - set(new_sources))
            self.sources = new_sources
            if added or removed:
                self.logger.info(
                    f"🔄 Sources reloaded: {len(new_sources)} total (+{added}, -{removed})"
                )
            else:
                self.logger.debug(f"🔄 Sources reloaded: {len(new_sources)} total (no changes)")
        except Exception as e:
            self.logger.error(f"Error reloading sources: {e}", exc_info=True)

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
        self.db_path = db_path  # Store for later use
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
        
        # ── gm_blocked_domains table (domain-level block tracking) ─────────────
        try:
            with eng.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS gm_blocked_domains (
                        domain      TEXT PRIMARY KEY,
                        blocked_count INTEGER DEFAULT 0,
                        is_blocked  INTEGER DEFAULT 0,
                        last_error  TEXT,
                        updated_at  TEXT
                    )
                """))
                conn.commit()
                self.logger.debug("gm_blocked_domains table ready")
        except Exception as e:
            self.logger.debug(f"Error creating gm_blocked_domains: {e}")

        # ── title_hash column on gm_articles ────────────────────────────────
        try:
            with eng.connect() as conn:
                result = conn.execute(text("PRAGMA table_info(gm_articles)")).fetchall()
                if 'title_hash' not in [r[1] for r in result]:
                    conn.execute(text('ALTER TABLE gm_articles ADD COLUMN title_hash TEXT'))
                    conn.execute(text('CREATE INDEX IF NOT EXISTS idx_articles_title_hash ON gm_articles(title_hash)'))
                    conn.commit()
                    self.logger.info("✅ title_hash column + index added to gm_articles")
        except Exception as e:
            self.logger.debug(f"Error adding title_hash: {e}")

        # ── idx_articles_enriched_translated ────────────────────────────────────
        # Covers: COUNT(*) WHERE is_enriched=x  and  COUNT(*) WHERE is_translated=x
        # Used by GET /api/queues to avoid full table scans.
        try:
            with eng.begin() as conn:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_articles_enriched_translated "
                    "ON gm_articles(is_enriched, is_translated)"
                ))
            self.logger.info("✅ Index idx_articles_enriched_translated ready")
        except Exception as e:
            self.logger.debug(f"Error creating idx_articles_enriched_translated: {e}")

        # ── v_articles_pending_enrichment (no ORDER BY — ORDER BY in worker query)
        # Simple equality on is_enriched=0 so SQLite uses
        # idx_articles_enriched_translated as a covering index for COUNT(*).
        try:
            with eng.begin() as conn:
                conn.execute(text("DROP VIEW IF EXISTS v_articles_pending_enrichment"))
                conn.execute(text("""
                    CREATE VIEW v_articles_pending_enrichment AS
                    SELECT
                        a.id_article,
                        a.id_source,
                        s.name   AS source_name,
                        a.url,
                        a.author,
                        a.description,
                        a.content,
                        a.urlToImage,
                        a.published_at_gmt
                    FROM gm_articles a
                    LEFT JOIN gm_sources s ON a.id_source = s.id_source
                    WHERE a.is_enriched = 0
                      AND a.url IS NOT NULL
                      AND a.url != ''
                      AND (s.fetch_blocked IS NULL OR s.fetch_blocked != 1)
                """))
            self.logger.info("✅ View v_articles_pending_enrichment ready")
        except Exception as e:
            self.logger.warning(f"Error creating v_articles_pending_enrichment: {e}")

        # ── v_articles_pending_translation (no ORDER BY — ORDER BY in worker query)
        # idx_articles_is_translated(is_translated, detected_language) covers the
        # initial filter; idx_languages_translate covers the JOIN.
        try:
            with eng.begin() as conn:
                conn.execute(text("DROP VIEW IF EXISTS v_articles_pending_translation"))
                conn.execute(text("""
                    CREATE VIEW v_articles_pending_translation AS
                    SELECT
                        a.id_article,
                        a.id_source,
                        s.name                              AS source_name,
                        a.title,
                        a.description,
                        a.content,
                        a.detected_language,
                        a.language_confidence,
                        l.language_name,
                        l.translate_to                      AS target_language,
                        l.translator_code,
                        l.translate_backend,
                        l.translate_without_enrichment,
                        a.inserted_at_ms,
                        a.published_at_gmt
                    FROM gm_articles a
                    JOIN languages l
                           ON a.detected_language = l.language_code
                          AND l.translate = 1
                    LEFT JOIN gm_sources s
                           ON a.id_source = s.id_source
                    WHERE a.is_translated = 0
                      AND a.title IS NOT NULL
                      AND a.title != ''
                      AND a.is_enriched IN (1, -1)
                """))
            self.logger.info("✅ View v_articles_pending_translation ready")
        except Exception as e:
            self.logger.warning(f"Error creating v_articles_pending_translation: {e}")
        # Efficient summary view: uses idx_articles_is_translated(is_translated,
        # detected_language) and idx_languages_translate(translate, language_code).
        try:
            with eng.begin() as conn:
                conn.execute(text("DROP VIEW IF EXISTS v_translation_pending_by_language"))
                conn.execute(text("""
                    CREATE VIEW v_translation_pending_by_language AS
                    SELECT
                        l.language_code,
                        l.language_name,
                        l.translate_backend,
                        l.translate_to                           AS target_language,
                        COUNT(*)                                 AS pending_count,
                        SUM(CASE WHEN a.is_enriched = 1 THEN 1 ELSE 0 END) AS enriched_pending,
                        SUM(CASE WHEN a.is_enriched = 0 THEN 1 ELSE 0 END) AS not_yet_enriched,
                        MIN(a.inserted_at_ms)                   AS oldest_pending_ms,
                        MAX(a.inserted_at_ms)                   AS newest_pending_ms
                    FROM languages l
                    JOIN gm_articles a
                           ON a.detected_language = l.language_code
                          AND a.is_translated = 0
                          AND a.title IS NOT NULL
                          AND a.title != ''
                    WHERE l.translate = 1
                    GROUP BY l.language_code, l.language_name, l.translate_backend, l.translate_to
                    ORDER BY pending_count DESC
                """))
            self.logger.info("✅ View v_translation_pending_by_language ready")
        except Exception as e:
            self.logger.warning(f"Error creating v_translation_pending_by_language: {e}")

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
                    # Check for feed tags (handle both bytes and str)
                    sample = content[:1000]
                    if isinstance(sample, bytes):
                        has_feed = any(tag in sample for tag in [b'<rss', b'<feed', b'<channel'])
                    else:
                        has_feed = any(tag in sample for tag in ['<rss', '<feed', '<channel'])
                    
                    if has_feed:
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
                _loop = asyncio.get_event_loop()
                feed = await _loop.run_in_executor(None, feedparser.parse, content)
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
                
                try:
                    if await self.db.insert_source_if_new(new_rss_source):
                        self.sources[rss_id] = {**new_rss_source, 'articles': {}}
                        self.logger.info(f"✅ Registered RSS source: {source_name} -> {rss_url}")
                except Exception as e:
                    self.logger.error(f"Failed to register RSS source {source_name}: {e}")
        except Exception as e:
            self.logger.debug(f"Could not discover RSS for {source_name}: {e}")
    
    async def update_source_timezone(self, source_id, detected_timezone):
        """
        Update source timezone when detected from article timestamps.
        Only updates if:
        - Detected timezone is different from configured timezone
        - Timezone is detected from actual article data (not inferred)
        
        Args:
            source_id: Source ID to update
            detected_timezone: Timezone detected from articles (e.g., 'UTC+05:30')
        """
        try:
            # Get current source info
            if source_id not in self.sources:
                return
            
            current_tz = self.sources[source_id].get('timezone')
            
            # Only update if different
            if current_tz == detected_timezone:
                return
            
            self.logger.info(f"🕐 Updating timezone for {self.sources[source_id].get('name')}: {current_tz} -> {detected_timezone}")
            
            try:
                await self.db.update_source_timezone(source_id, detected_timezone)
                # Update in-memory sources
                self.sources[source_id]['timezone'] = detected_timezone
            except Exception as e:
                self.logger.error(f"Failed to update timezone for {source_id}: {e}")
        except Exception as e:
            self.logger.debug(f"Error updating source timezone for {source_id}: {e}")
    
    async def backfill_missing_gmt_for_source(self, source_id, detected_timezone):
        """
        Backfill published_at_gmt for articles from this source that are missing it.
        Called after updating source timezone to correct historical articles.
        
        Args:
            source_id: Source ID to backfill
            detected_timezone: Timezone to apply (e.g., 'UTC+05:30')
        """
        try:
            source_name = self.sources[source_id].get('name', source_id)
            
            # Parse timezone offset from string like 'UTC+05:30' to tzoffset
            from dateutil.tz import tzoffset
            
            # Extract offset string (+05:30 or -05:30)
            tz_match = re.search(r'([+-])(\d{2}):(\d{2})', detected_timezone)
            if not tz_match:
                self.logger.warning(f"⚠️  [{source_name}] Invalid timezone format: {detected_timezone}")
                return
            
            sign = 1 if tz_match.group(1) == '+' else -1
            hours = int(tz_match.group(2))
            minutes = int(tz_match.group(3))
            total_seconds = sign * (hours * 3600 + minutes * 60)
            tz_offset = tzoffset('', total_seconds)
            
            articles_to_fix = await self.db.fetch_articles_missing_gmt(source_id)

            if not articles_to_fix:
                return

            self.logger.info(f"🔄 [{source_name}] Backfilling {len(articles_to_fix)} articles with timezone {detected_timezone}")

            # Process conversions
            updates = []
            failed = 0

            for article_id, timestamp_str in articles_to_fix:
                try:
                    dt_naive      = dateutil_parser.parse(timestamp_str)
                    dt_with_tz    = dt_naive.replace(tzinfo=tz_offset)
                    dt_utc        = dt_with_tz.astimezone(pytz.UTC)
                    gmt_timestamp = dt_utc.replace(microsecond=0).isoformat()
                    updates.append({'article_id': article_id, 'gmt_timestamp': gmt_timestamp})
                except Exception as e:
                    failed += 1
                    self.logger.debug(f"Failed to convert timestamp for article {article_id}: {e}")

            if updates:
                await self.db.update_gmt_batch(updates)
                self.logger.info(f"✅ [{source_name}] Backfilled {len(updates)} articles ({failed} failed)")
        except Exception as e:
            self.logger.debug(f"Error during GMT backfill for {source_id}: {e}")
    
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
                                
                                # PHASE 1: Agrupar artigos por fonte e detectar problemas de fuso
                                articles_by_source = {}
                                for article in articles:
                                    article_source = article.get('source', {})
                                    article_source_id = article_source.get('id')
                                    article_source_name = article_source.get('name', '')
                                    source_id = article_source_name if article_source_id is None else article_source_id
                                    
                                    if source_id not in articles_by_source:
                                        articles_by_source[source_id] = {
                                            'name': article_source_name,
                                            'articles': [],
                                            'timestamps': []
                                        }
                                    
                                    articles_by_source[source_id]['articles'].append(article)
                                    if article.get('publishedAt'):
                                        articles_by_source[source_id]['timestamps'].append(article['publishedAt'])
                                
                                # Detectar fuso incorreto para cada fonte
                                for source_id, source_info in articles_by_source.items():
                                    if source_id in self.sources and self.sources[source_id].get('use_timezone', 0) == 0:
                                        # Só detectar se não foi configurado manualmente
                                        corrected_tz, should_enable = detect_timezone_from_articles(
                                            source_info['timestamps'],
                                            source_name=source_info['name'],
                                            logger=self.logger
                                        )
                                        
                                        if corrected_tz and should_enable:
                                            # Atualizar banco de dados
                                            try:
                                                async with aiosqlite.connect(self.db_path) as db:
                                                    await db.execute(
                                                        'UPDATE gm_sources SET timezone = ?, use_timezone = 1 WHERE id_source = ?',
                                                        (corrected_tz, source_id)
                                                    )
                                                    await db.commit()
                                                
                                                # Atualizar cache em memória
                                                if source_id in self.sources:
                                                    self.sources[source_id]['timezone'] = corrected_tz
                                                    self.sources[source_id]['use_timezone'] = 1
                                                
                                                self.logger.info(
                                                    f"✅ [{source_info['name']}] Fuso corrigido para {corrected_tz}, use_timezone=1"
                                                )
                                            except Exception as e:
                                                self.logger.error(f"Failed to update timezone for {source_info['name']}: {e}")
                                
                                # PHASE 2: Processar artigos com fuso já corrigido
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
                                    
                                    # Sanitize HTML in description and content
                                    if article_description:
                                        article_description = sanitize_html_content(article_description)
                                    
                                    if article_content:
                                        article_content = sanitize_html_content(article_content)
                                    
                                    # Extract first image from description if urlToImage is missing
                                    # Also remove the image from HTML to avoid displaying twice
                                    if not article_urlToImage and article_description:
                                        article_urlToImage, article_description = extract_and_remove_first_image(article_description)
                                        article_urlToImage = article_urlToImage or ''
                                    
                                    # Get source timezone if available
                                    source_tz = self.sources.get(source_id, {}).get('timezone')
                                    
                                    # Create normalized UTC version (article timezone has priority over source timezone)
                                    # Use source timezone only if use_timezone flag is enabled
                                    use_tz = self.sources.get(source_id, {}).get('use_timezone', 0)
                                    article_publishedAt_gmt, detected_tz = normalize_timestamp_to_utc(article_publishedAt, source_tz, use_source_timezone=(use_tz == 1))
                                    
                                    # Update source timezone if detected from article and different from configured
                                    if detected_tz and source_tz != detected_tz:
                                        self.loop.create_task(self.update_source_timezone(source_id, detected_tz))
                                    
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

                                        try:
                                            await self.db.insert_source_if_new(new_source)
                                            sources_added += 1
                                            self.logger.info(f"✅ Added source: {source_name}")
                                            # Try to discover RSS feed
                                            if source_url:
                                                self.loop.create_task(
                                                    self.register_rss_source(session, source_id, source_name, source_url)
                                                )
                                        except Exception as e:
                                            self.logger.error(f"Failed to insert source {source_name}: {e}")
                                    
                                    # NewsAPI requests are per-language (the `lang` loop variable).
                                    # Use it directly — no need for langdetect on a title-only article.
                                    detected_lang, lang_confidence = lang, 1.0

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
                                        'content': article_content,
                                        'inserted_at_ms': int(time.time() * 1000),  # Insertion timestamp in ms
                                        'detected_language': detected_lang,
                                        'language_confidence': lang_confidence,
                                        'is_enriched': 0,
                                    }

                                    if await self.enrich_article_content(new_article, source_name, source_id):
                                        new_article['is_enriched'] = 1

                                    try:
                                        if await self.db.insert_article(new_article):
                                            articles_inserted += 1
                                            self.logger.debug(f"✅ [{source_name}] {article_title[:60]}...")
                                        else:
                                            articles_skipped += 1
                                            self.logger.debug(f"⏭️  [{source_name}] Already exists: {article_title[:40]}...")
                                    except Exception as e:
                                        self.logger.error(f"Failed to insert article '{article_title[:40]}...': {e}")
                                
                                self.logger.info(f"Summary NewsAPI {lang}: {articles_inserted} inserted, {articles_skipped} skipped, {sources_added} new sources")
                        
                        except aiohttp.ClientError as e:
                            self.logger.error(f"Network error fetching NewsAPI {lang}: {e}")
                        except json.JSONDecodeError as e:
                            self.logger.error(f"JSON decode error for NewsAPI {lang}: {e}")
                        except Exception as e:
                            self.logger.error(f"Unexpected error processing NewsAPI {lang}: {e}", exc_info=True)
                
                if not self.shutdown_flag:
                    self.logger.info(f"NewsAPI cycle {cycle_count} complete. Sleeping {NEWSAPI_CYCLE_INTERVAL}s...")
                    # Reload sources to pick up any database changes
                    await self.reload_sources()
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
                
                # Get all RSS sources from database (skip fetch_blocked sources)
                raw_sources = await self.db.load_rss_sources(skip_blocked=True)
                rss_sources = [
                    {
                        'id':       r['id_source'],
                        'name':     r['name'],
                        'url':      r['url'],
                        'language': r.get('language') or 'en',
                    }
                    for r in raw_sources
                ]
                
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
                    # Reload sources to pick up any database changes
                    await self.reload_sources()
                    await asyncio.sleep(RSS_CYCLE_INTERVAL)
        except asyncio.CancelledError:
            self.logger.info("📡 RSS collector cancelled")
        finally:
            self.logger.info("📡 RSS collector stopped")
    
    async def process_rss_feed_with_semaphore(self, session, source, semaphore):
        """
        Process RSS feed with semaphore control and a hard per-feed timeout.
        The hard timeout (RSS_TIMEOUT * 3) guarantees the batch progresses even
        if a feed TCP-hangs beyond the inner aiohttp/curl timeouts.
        """
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    self.process_rss_feed(session, source),
                    timeout=RSS_TIMEOUT * 3
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"⏱️  [{source['name']}] Hard timeout ({RSS_TIMEOUT * 3}s) — skipping feed"
                )
    
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
                _loop = asyncio.get_event_loop()
                feed = await _loop.run_in_executor(None, feedparser.parse, content)
            except (AssertionError, ValueError, Exception) as parse_err:
                # feedparser can raise AssertionError on malformed HTML/XML in marked sections
                self.logger.debug(f"⚠️  [{source_name}] Parser error (malformed feed): {parse_err}")
                return
                
            if not feed.entries:
                self.logger.debug(f"⚠️  [{source_name}] No entries found")
                return
            
            self.logger.debug(f"📥 [{source_name}] Received {len(feed.entries)} entries")
            
            # PHASE 1: Análise de fuso horário ANTES de processar artigos
            # Coleta todos os timestamps para detectar se o fuso está incorreto
            all_timestamps = []
            for entry in feed.entries:
                published = as_text(entry.get('published', entry.get('updated', '')))
                if published:
                    all_timestamps.append(published)
            
            # Detecta se há problema de fuso horário analisando todos os timestamps
            if all_timestamps and source_id in self.sources:
                current_use_tz = self.sources[source_id].get('use_timezone', 0)
                
                # Só fazer auto-correção se use_timezone não estiver manualmente configurado
                if current_use_tz == 0:
                    corrected_tz, should_enable = detect_timezone_from_articles(
                        all_timestamps, 
                        source_name=source_name,
                        logger=self.logger
                    )
                    
                    if corrected_tz and should_enable:
                        # Atualizar banco de dados ANTES de processar artigos
                        try:
                            async with aiosqlite.connect(self.db_path) as db:
                                await db.execute(
                                    'UPDATE gm_sources SET timezone = ?, use_timezone = 1 WHERE id_source = ?',
                                    (corrected_tz, source_id)
                                )
                                await db.commit()
                            
                            # Atualizar cache em memória
                            self.sources[source_id]['timezone'] = corrected_tz
                            self.sources[source_id]['use_timezone'] = 1
                            
                            self.logger.info(
                                f"✅ [{source_name}] Fuso corrigido para {corrected_tz}, use_timezone=1. "
                                f"Artigos serão inseridos com timestamps corretos."
                            )
                        except Exception as e:
                            self.logger.error(f"Failed to update timezone for {source_name}: {e}")
            
            # PHASE 2: Processar artigos com fuso já corrigido
            articles_inserted = 0
            articles_skipped = 0
            detected_timezones = []  # Track detected timezones from all articles
            
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
                    
                    # Create normalized UTC version (article timezone has priority over source timezone)
                    source_tz = source.get('timezone')
                    # Use source timezone only if use_timezone flag is enabled
                    use_tz = source.get('use_timezone', 0)
                    published_gmt, detected_tz = normalize_timestamp_to_utc(published, source_tz, use_source_timezone=(use_tz == 1))
                    
                    # Track detected timezone for consistency check
                    if detected_tz:
                        detected_timezones.append(detected_tz)
                    
                    # Generate article key with original timestamp
                    article_key = url_encode(title + url + published)
                    
                    # Sanitize HTML description
                    clean_description = sanitize_html_content(description) if description else ''
                    
                    # Extract first image from description and remove it from HTML to avoid duplicates
                    extracted_image_url, clean_description = extract_and_remove_first_image(clean_description) if clean_description else (None, clean_description)
                    
                    # Language detection — prefer declared source/feed language over
                    # automatic detection.  Short titles (e.g. author names, column
                    # headers) are frequently mis-classified by langdetect, and many
                    # feeds already declare their language either in the DB source
                    # record or in the RSS <language> element.
                    #
                    # Priority:
                    #   1. gm_sources.language (manually/auto set when source created)
                    #   2. <language> element in the RSS feed itself
                    #   3. Automatic langdetect (fallback)
                    _source_declared_lang = (source.get('language') or '').strip().lower()
                    if not _source_declared_lang:
                        # Try the RSS feed's own <language> tag (e.g. "pt-br" → "pt")
                        _feed_lang_raw = (feed.feed.get('language') or '').strip().lower()
                        _source_declared_lang = _feed_lang_raw[:2] if _feed_lang_raw else ''

                    if _source_declared_lang:
                        # Source language is known — use it directly with full confidence.
                        detected_lang, lang_confidence = _source_declared_lang, 1.0
                    else:
                        detected_lang, lang_confidence = detect_article_language(title, clean_description)

                    # Create article object
                    new_article = {
                        'id_article': article_key,
                        'id_source': source_id,
                        'author': author,
                        'title': title,
                        'description': clean_description,
                        'url': url,
                        'urlToImage': extracted_image_url or '',
                        'publishedAt': published,  # Original with timezone
                        'published_at_gmt': published_gmt,  # Normalized UTC
                        'content': '',
                        'inserted_at_ms': int(time.time() * 1000),  # Insertion timestamp in ms
                        'detected_language': detected_lang,
                        'language_confidence': lang_confidence,
                        'is_enriched': 0,
                        'title_hash': _make_title_hash(title),
                    }

                    t_hash = new_article['title_hash']
                    if t_hash:
                        existing = await self.db.find_by_title_hash(t_hash)
                        if existing:
                            new_article['author']      = existing['author']      or new_article['author']
                            new_article['description'] = existing['description'] or new_article['description']
                            new_article['content']     = existing['content']
                            new_article['urlToImage']  = existing['urlToImage']  or new_article['urlToImage']
                            new_article['is_enriched'] = 1

                    # Inline enrichment intentionally removed from RSS pipeline:
                    # asyncio.wait_for (Python 3.11) awaits playwright cleanup on cancel,
                    # keeping the semaphore slot occupied 3+ minutes per timed-out feed.
                    # The backfill worker (_backfill_consumer) handles is_enriched=0 articles.

                    # Insert article
                    try:
                        if await self.db.insert_article(new_article):
                            articles_inserted += 1
                            if articles_inserted <= 5:  # Log first 5
                                self.logger.debug(f"  ✅ [{source_name}] {title[:60]}...")
                        else:
                            articles_skipped += 1
                    except Exception as e:
                        self.logger.error(f"Failed to insert RSS article: {e}")
                
            if articles_inserted > 0:
                self.logger.debug(f"✅ [{source_name}] {articles_inserted} new, {articles_skipped} existing")
            else:
                self.logger.debug(f"⏭️  [{source_name}] All {articles_skipped} articles already exist")
            
            # Check if all articles in the feed have the same timezone
            # If yes, and it's different from source timezone, update it
            # Only do automatic backfill if use_timezone is enabled for this source
            if detected_timezones:
                unique_timezones = set(detected_timezones)
                if len(unique_timezones) == 1:
                    # All articles have the same timezone
                    consistent_tz = detected_timezones[0]
                    source_tz = source.get('timezone')
                    use_tz = source.get('use_timezone', 0)
                    
                    if source_tz != consistent_tz:
                        # Update source timezone with the consistent value from articles
                        self.logger.info(f"🕐 [{source_name}] All {len(detected_timezones)} articles have timezone {consistent_tz}, updating source")
                        await self.update_source_timezone(source_id, consistent_tz)
                        
                        # Only backfill if use_timezone is enabled (manually confirmed sources)
                        if use_tz == 1:
                            self.logger.info(f"🔄 [{source_name}] use_timezone=1, backfilling historical articles")
                            await self.backfill_missing_gmt_for_source(source_id, consistent_tz)
                        else:
                            self.logger.info(f"⏸️  [{source_name}] use_timezone=0, skipping automatic backfill (needs manual confirmation)")
                elif len(unique_timezones) > 1:
                    # Multiple different timezones detected - log for debugging
                    self.logger.debug(f"⚠️  [{source_name}] Multiple timezones in feed: {unique_timezones}")
                    
        except asyncio.TimeoutError:
            self.logger.warning(f"⏱️  [{source_name}] Timeout after {RSS_TIMEOUT}s")
        except Exception as e:
            self.logger.error(f"❌ [{source_name}] Error: {str(e)[:100]}")
    
    async def collect_mediastack(self):
        """
        Collect articles from MediaStack API with rate limiting in continuous loop.
        Free tier: 100 requests/month per key (~3 keys = 300/month)
        Strategy: Collect PT, ES, IT (EN covered by NewsAPI)
        """
        self.logger.info("🌍 MediaStack collector started")
        cycle_count = 0
        
        # Languages to collect (EN already covered by NewsAPI)
        languages = ['pt', 'es', 'it']
        
        try:
            while not self.shutdown_flag:
                cycle_count += 1
                # Rotate MediaStack key each cycle to spread monthly quota across accounts
                mediastack_key = MEDIASTACK_API_KEYS[self.current_mediastack_key_index]
                self.current_mediastack_key_index = (self.current_mediastack_key_index + 1) % len(MEDIASTACK_API_KEYS)
                self.logger.info(f"🌍 MediaStack Cycle {cycle_count} starting (key #{self.current_mediastack_key_index})...")
                
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
                                'access_key': mediastack_key,
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
                                    
                                    # PHASE 1: Agrupar artigos por fonte e detectar problemas de fuso
                                    articles_by_source = {}
                                    for article_data in articles:
                                        source_name = article_data.get('source', 'unknown').strip()
                                        source_id = f"mediastack-{source_name.lower().replace(' ', '-').replace('_', '-')}"
                                        
                                        if source_id not in articles_by_source:
                                            articles_by_source[source_id] = {
                                                'name': source_name,
                                                'articles': [],
                                                'timestamps': []
                                            }
                                        
                                        articles_by_source[source_id]['articles'].append(article_data)
                                        if article_data.get('published_at'):
                                            articles_by_source[source_id]['timestamps'].append(article_data['published_at'])
                                    
                                    # Detectar fuso incorreto para cada fonte
                                    for source_id, source_info in articles_by_source.items():
                                        if source_id in self.sources and self.sources[source_id].get('use_timezone', 0) == 0:
                                            # Só detectar se não foi configurado manualmente
                                            corrected_tz, should_enable = detect_timezone_from_articles(
                                                source_info['timestamps'],
                                                source_name=f"MediaStack-{source_info['name']}",
                                                logger=self.logger
                                            )
                                            
                                            if corrected_tz and should_enable:
                                                # Atualizar banco de dados
                                                try:
                                                    async with aiosqlite.connect(self.db_path) as db:
                                                        await db.execute(
                                                            'UPDATE gm_sources SET timezone = ?, use_timezone = 1 WHERE id_source = ?',
                                                            (corrected_tz, source_id)
                                                        )
                                                        await db.commit()
                                                    
                                                    # Atualizar cache em memória
                                                    if source_id in self.sources:
                                                        self.sources[source_id]['timezone'] = corrected_tz
                                                        self.sources[source_id]['use_timezone'] = 1
                                                    
                                                    self.logger.info(
                                                        f"✅ [MediaStack-{source_info['name']}] Fuso corrigido para {corrected_tz}, use_timezone=1"
                                                    )
                                                except Exception as e:
                                                    self.logger.error(f"Failed to update timezone for MediaStack-{source_info['name']}: {e}")
                                    
                                    # PHASE 2: Processar artigos com fuso já corrigido
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
                    # Reload sources to pick up any database changes
                    await self.reload_sources()
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
            
            # Create source ID (mediastack-source_name)
            source_id = f"mediastack-{source_name.lower().replace(' ', '-').replace('_', '-')}"
            
            # Get source timezone if available
            source_tz = self.sources.get(source_id, {}).get('timezone')
            
            # Create normalized UTC version (article timezone has priority over source timezone)
            # Use source timezone only if use_timezone flag is enabled
            use_tz = self.sources.get(source_id, {}).get('use_timezone', 0)
            published_at_gmt, detected_tz = normalize_timestamp_to_utc(published_at, source_tz, use_source_timezone=(use_tz == 1))
            
            # Update source timezone if detected from article and different from configured
            if detected_tz and source_tz != detected_tz:
                self.loop.create_task(self.update_source_timezone(source_id, detected_tz))
            
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
            # Sanitize HTML in description
            clean_description = sanitize_html_content(description) if description else ''
            
            # Extract first image from description if image field is empty
            # Also remove image from HTML to avoid duplicates
            extracted_image = None
            if not image and clean_description:
                extracted_image, clean_description = extract_and_remove_first_image(clean_description)
            
            # MediaStack requests are per-language (the `language` loop variable).
            # Use it directly — no need for langdetect on a title-only article.
            detected_lang, lang_confidence = language, 1.0

            new_article = {
                'id_article': article_id,
                'id_source': source_id,
                'author': author[:200] if author else '',
                'title': title[:500] if title else '',
                'description': clean_description if clean_description else '',
                'url': url[:500] if url else '',
                'urlToImage': (extracted_image or image or '')[:500],
                'publishedAt': published_at,  # Original with timezone
                'published_at_gmt': published_at_gmt,  # Normalized UTC
                'content': '',
                'inserted_at_ms': int(time.time() * 1000),  # Insertion timestamp in ms
                'detected_language': detected_lang,
                'language_confidence': lang_confidence,
                'is_enriched': 0,
                'title_hash': _make_title_hash(title),
            }

            if await self.enrich_article_content(new_article, source_name, source_id):
                new_article['is_enriched'] = 1

            # Insert article with lock
            try:
                inserted = await self.db.insert_article(new_article)
                if inserted:
                    self.logger.debug(f"  ✅ MediaStack: {title[:60]}...")
                    return 'inserted'
                return 'skipped'
            except Exception as e:
                self.logger.error(f"Failed to insert MediaStack article: {e}")
                return 'error'
        
        except Exception as e:
            self.logger.error(f"Error processing MediaStack article: {str(e)}")
            return 'error'
    
    async def ensure_mediastack_source_exists(self, source_id, source_name, language, category, source_url=''):
        """
        Ensure MediaStack source exists in database.
        Returns: True if source was newly created, False if it already existed
        """
        source = {
            'id_source':   source_id,
            'name':        source_name,
            'description': 'MediaStack news source',
            'url':         source_url,
            'category':    category,
            'language':    language,
            'country':     '',
        }
        try:
            is_new = await self.db.insert_source_if_new(source)
            if is_new:
                self.logger.info(f"✅ Created MediaStack source: {source_name} ({source_url})")
            return is_new
        except Exception as e:
            self.logger.error(f"Error ensuring MediaStack source exists: {e}")
            return False
    
    async def backfill_content(self):
        """
        Tiered enrichment pipeline: cffi → requests → playwright.

        Three independent producer+consumer pairs run concurrently, each with
        its own semaphore, concurrency, and timeout:
          Tier 0 (cffi)      — enrich_try=0  fast Chrome-TLS fetcher
          Tier 1 (requests)  — enrich_try=1  browser-headers fallback
          Tier 2 (playwright)— enrich_try=2  headless Chromium last resort

        A failure in tier N increments enrich_try so the article moves to tier
        N+1 on the next cycle.  Playwright failure marks is_enriched=-1 (done).
        """
        if not BACKFILL_ENABLED:
            self.logger.info("⏭️  Backfill disabled (BACKFILL_ENABLED=False)")
            return

        self.logger.info(
            f"🔁 Backfill started — "
            f"cffi(batch={CFFI_BATCH_SIZE}, concur={CFFI_CONCURRENCY}, t={CFFI_TIMEOUT}s) | "
            f"requests(batch={REQUESTS_BATCH_SIZE}, concur={REQUESTS_CONCURRENCY}, t={REQUESTS_TIMEOUT}s) | "
            f"playwright(batch={PLAYWRIGHT_BATCH_SIZE}, concur={PLAYWRIGHT_CONCURRENCY}, t={PLAYWRIGHT_TIMEOUT}s)"
        )

        # Shared in-flight tracking (keyed per worker instance)
        cffi_ids:       set[int] = set()
        requests_ids:   set[int] = set()
        playwright_ids: set[int] = set()
        self._backfill_processing_ids = cffi_ids  # expose largest set for /api/queues

        cffi_inflight       = asyncio.Semaphore(CFFI_BATCH_SIZE)
        requests_inflight   = asyncio.Semaphore(REQUESTS_BATCH_SIZE)
        playwright_inflight = asyncio.Semaphore(PLAYWRIGHT_BATCH_SIZE)

        await asyncio.gather(
            self._backfill_producer(cffi_inflight,       cffi_ids,       self._cffi_worker,       enrich_try=0, batch=CFFI_BATCH_SIZE),
            self._backfill_consumer(cffi_inflight,       cffi_ids,       self._cffi_worker,       enrich_try=0),
            self._backfill_producer(requests_inflight,   requests_ids,   self._requests_worker,   enrich_try=1, batch=REQUESTS_BATCH_SIZE),
            self._backfill_consumer(requests_inflight,   requests_ids,   self._requests_worker,   enrich_try=1),
            self._backfill_producer(playwright_inflight, playwright_ids, self._playwright_worker, enrich_try=2, batch=PLAYWRIGHT_BATCH_SIZE),
            self._backfill_consumer(playwright_inflight, playwright_ids, self._playwright_worker, enrich_try=2),
            return_exceptions=True,
        )

    async def _backfill_producer(
        self,
        inflight: asyncio.Semaphore,
        processing_ids: set[int],
        worker,
        enrich_try: int,
        batch: int,
    ) -> None:
        """
        Fetch pending articles for *enrich_try* tier from DB and enqueue them.
        Blocks on the semaphore when *batch* articles are already in-flight.
        Sleeps BACKFILL_CYCLE_INTERVAL when the DB returns no new rows.
        """
        while not self.shutdown_flag:
            try:
                # ── 0. Bulk-close articles from blocked sources ────────────
                await self.db.bulk_close_blocked_source_articles()

                # ── 1. Fetch a larger slice so that after excluding in-flight
                #       articles we still have enough work to fill free slots. ─
                fetch_limit = batch + len(processing_ids)
                rows = await self.db.fetch_pending_enrichment(fetch_limit, enrich_try=enrich_try)

                # Exclude articles already queued / being processed
                rows = [r for r in rows if r['id_article'] not in processing_ids]

                if not rows:
                    self.logger.info(
                        f"✅ Backfill[{worker.backend}]: no new articles — "
                        f"sleeping {BACKFILL_CYCLE_INTERVAL}s "
                        f"(in-flight={len(processing_ids)})"
                    )
                    await asyncio.sleep(BACKFILL_CYCLE_INTERVAL)
                    continue

                self.logger.info(
                    f"🔁 Backfill[{worker.backend}]: {len(rows)} articles to enqueue "
                    f"(in-flight={len(processing_ids)}, max={batch})…"
                )

                for row in rows:
                    if self.shutdown_flag:
                        return

                    await inflight.acquire()

                    article = {
                        'id_article':  row['id_article'],
                        'id_source':   row['id_source']   or '',
                        'source_name': row['source_name'] or row['id_source'] or '',
                        'url':         row['url'],
                        'author':      row['author'],
                        'description': row['description'],
                        'content':     row['content'],
                        'urlToImage':  row['urlToImage'],
                        '_enrich_try': row.get('enrich_try', enrich_try),
                    }
                    processing_ids.add(article['id_article'])
                    await worker.enqueue(article)

                # Yield to let the consumer (and other tasks) run
                await asyncio.sleep(0)

            except asyncio.CancelledError:
                self.logger.info(f"🏁 Backfill[{worker.backend}] producer cancelled")
                return
            except Exception as exc:
                self.logger.error(f"Backfill[{worker.backend}] producer error: {exc}", exc_info=True)
                await asyncio.sleep(60)

    async def _backfill_consumer(
        self,
        inflight: asyncio.Semaphore,
        processing_ids: set[int],
        worker,
        enrich_try: int,
    ) -> None:
        """
        Drain the worker's output_queue and persist results to the DB.
        On failure, advances the article to the next tier via mark_enrich_attempt_failed().
        """
        enriched_total = 0
        failed_total = 0

        while not self.shutdown_flag:
            try:
                try:
                    article_dict, ok = await asyncio.wait_for(
                        worker.output_queue.get(),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    continue

                article_id  = article_dict['id_article']
                source_id   = article_dict.get('id_source', '')
                source_name = article_dict.get('source_name', '')
                current_try = article_dict.get('_enrich_try', enrich_try)

                # Remove from tracking set and free the inflight slot
                processing_ids.discard(article_id)
                inflight.release()

                # Persist blocking error — use the article's URL *domain* so
                # aggregator feeds (e.g. investing.com's "All News") are never
                # blocked; only the actual paywalled domain gets blocked.
                error_code     = article_dict.pop('_error_code', None)
                blocked_domain = article_dict.pop('_blocked_domain', None)
                if error_code:
                    if blocked_domain:
                        await self._increment_blocked_domain(
                            blocked_domain, source_name, error_code
                        )
                    elif source_id:
                        # Fallback (no URL available): block by source
                        await self._increment_blocked_count(source_id, source_name, error_code)

                if ok:
                    try:
                        # Normalize empty strings to NULL so content IS NOT NULL
                        # is a reliable "has real content" check downstream.
                        fetched_content     = article_dict.get('content') or None
                        fetched_author      = article_dict.get('author') or None
                        fetched_image       = article_dict.get('urlToImage') or None

                        # Use plain-text length to decide if description is
                        # meaningful — avoids stub HTML like HN's
                        # "<a href=...>Comments</a>" counting as real content.
                        raw_desc = article_dict.get('description') or ''
                        _desc_text = re.sub(r'<[^>]+>', '', raw_desc).strip()
                        fetched_description = raw_desc if len(_desc_text) >= 80 else None

                        # If the fetch "succeeded" but returned nothing useful,
                        # advance to next tier (same as a fetch failure).
                        if not fetched_content and not fetched_description:
                            self.logger.debug(
                                f"⚠️  Backfill[{worker.backend}]: empty result for [{source_name}] "
                                f"{article_id} — advancing to next tier"
                            )
                            await self.db.mark_enrich_attempt_failed(article_id, current_try)
                            continue
                        else:
                            enriched_val = 1

                        await self.db.save_enriched_article(
                            article_id,
                            author=fetched_author,
                            description=fetched_description,
                            content=fetched_content,
                            url_to_image=fetched_image,
                            is_enriched=enriched_val,
                        )
                        if enriched_val == 1:
                            enriched_total += 1
                        self.logger.debug(
                            f"✅ Backfill saved: [{source_name}] {article_id} "
                            f"(enriched={enriched_total}, val={enriched_val})"
                        )
                    except Exception as exc:
                        self.logger.error(
                            f"Backfill DB write failed for {article_id}: {exc}"
                        )
                else:
                    # Fetch failed → advance article to next tier
                    try:
                        await self.db.mark_enrich_attempt_failed(article_id, current_try)
                    except Exception as exc:
                        self.logger.error(f"Backfill failed-update error: {exc}")
                    failed_total += 1
                    next_tier = 'give up (is_enriched=-1)' if current_try >= 2 else f'tier {current_try + 1}'
                    self.logger.debug(
                        f"⚠️  Backfill[{worker.backend}] no-data: [{source_name}] {article_id} "
                        f"→ {next_tier} (failed={failed_total})"
                    )

            except asyncio.CancelledError:
                self.logger.info(
                    f"🏁 Backfill[{worker.backend}] consumer cancelled "
                    f"(enriched={enriched_total}, failed={failed_total})"
                )
                return
            except Exception as exc:
                self.logger.error(f"Backfill[{worker.backend}] consumer error: {exc}", exc_info=True)
                await asyncio.sleep(1)

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
        
        # Check if content is missing (handle None values with "or ''")
        has_author = (article_dict.get('author') or '').strip()
        has_description = (article_dict.get('description') or '').strip()
        has_content = (article_dict.get('content') or '').strip()
        url = (article_dict.get('url') or '').strip()
        
        # If we already have everything, skip fetching
        if has_author and has_description and has_content:
            return False
        
        # If no URL, can't fetch
        if not url:
            return False
        
        # Check if this source is blocked (403s)
        if source_id:
            try:
                fetch_blocked, blocked_count = await self.db.get_source_block_status(source_id)
                if fetch_blocked == 1:
                    self.logger.debug(
                        f"⏭️  [{source_name}] Skipping fetch - "
                        f"source is blocklisted (403 count: {blocked_count})"
                    )
                    return False
            except Exception as e:
                self.logger.debug(f"Could not check blocklist for {source_name}: {e}")
        
        # Attempt to fetch content
        try:
            self.logger.debug(f"🔍 [{source_name}] Attempting to fetch missing content from URL...")
            
            result = await fetch_article_content_async(url, ENRICH_TIMEOUT)
            
            # Only permanently-blocked requests count against the source.
            # Temporary errors (timeouts, 500/503) do not cause blocking.
            if result and result.get('error_type') == ERROR_PERMANENT:
                if source_id:
                    await self._increment_blocked_count(source_id, source_name, result.get('error_code'))
            
            if result and result.get('success'):
                updated = []
                
                # Update author if missing
                if not has_author and result.get('author'):
                    article_dict['author'] = result['author'][:200]
                    updated.append('author')
                
                # Update description if missing (sanitize HTML)
                if not has_description and result.get('description'):
                    clean_desc = sanitize_html_content(result['description'])
                    article_dict['description'] = clean_desc if clean_desc else ''
                    updated.append('description')
                
                # Update content if missing (sanitize HTML)
                if not has_content and result.get('content'):
                    clean_content = sanitize_html_content(result['content'])
                    article_dict['content'] = clean_content if clean_content else ''
                    updated.append('content')
                
                # Extract image from description if urlToImage is still empty
                # Also remove image from HTML to avoid duplicates
                if not article_dict.get('urlToImage') and article_dict.get('description'):
                    img_url, clean_desc = extract_and_remove_first_image(article_dict['description'])
                    if img_url:
                        article_dict['urlToImage'] = img_url
                        article_dict['description'] = clean_desc  # Update with cleaned HTML
                        updated.append('urlToImage')
                
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
            await self.db.increment_source_blocked_count(source_id, source_name, error_code)
        except Exception as e:
            self.logger.debug(f"Could not update blocked_count for {source_name}: {e}")

    async def _increment_blocked_domain(
        self, domain: str, source_name: str = '', error_code: Any = 403
    ) -> None:
        """
        Increment the blocked_count for an article *URL domain* in gm_blocked_domains.
        Once the threshold is reached, the domain is marked blocked and all pending
        articles whose URL contains that domain are removed from the enrichment queue
        (is_enriched = -1).  The RSS feed source in gm_sources is NOT touched.
        """
        if not domain:
            return
        try:
            count, is_blocked = await self.db.increment_blocked_domain(domain, error_code)
            if is_blocked:
                removed = await self.db.bulk_remove_pending_for_domain(domain)
                if removed > 0:
                    self.logger.warning(
                        f"🚫 Domain '{domain}' blocked after {count} "
                        f"HTTP {error_code} errors — "
                        f"{removed} pending articles removed from queue"
                    )
        except Exception as e:
            self.logger.debug(f"Could not update blocked domain '{domain}': {e}")

    async def probe_blocked_sources(self):
        """
        Periodically re-tests blocked sources by fetching a recent article URL.

        Sources are probed in ascending blocked_count order (lowest first) so
        that transiently blocked sources — those that hit the threshold due to
        a brief outage — are retried before persistently unresponsive ones.

        On success:
          - source is unblocked (fetch_blocked=0, blocked_count=0)
          - all non-enriched articles for that source are reset to is_enriched=0
            so the backfill pipeline picks them up again

        Cycle interval: PROBE_CYCLE_INTERVAL (default 1 h)
        Delay between probes: PROBE_DELAY (default 2 s)
        Configurable via env: PROBE_ENABLED, PROBE_CYCLE_INTERVAL, PROBE_DELAY,
                              PROBE_TIMEOUT
        """
        if not PROBE_ENABLED:
            self.logger.info("⏭️  Probe blocked sources disabled (PROBE_ENABLED=False)")
            return

        self.logger.info(
            f"🔍 Probe blocked sources started — "
            f"cycle={PROBE_CYCLE_INTERVAL}s, delay={PROBE_DELAY}s, "
            f"timeout={PROBE_TIMEOUT}s"
        )

        while True:
            try:
                # ── Collect blocked sources ────────────────────────────────
                rows = await self.db.get_blocked_sources_for_probe()

                if not rows:
                    self.logger.debug("🔍 Probe: no blocked sources — sleeping")
                    await asyncio.sleep(PROBE_CYCLE_INTERVAL)
                    continue

                self.logger.info(f"🔍 Probe: testing {len(rows)} blocked source(s)…")
                unblocked_count = 0

                for row in rows:
                    source_id   = row['id_source']
                    source_name = row['name'] or source_id
                    count       = row['blocked_count']
                    url         = row['sample_url']

                    try:
                        result = await fetch_article_content_async(url, PROBE_TIMEOUT)

                        if result and result.get('success'):
                            self.logger.info(
                                f"✅ [{source_name}] probe succeeded — "
                                f"unblocking (was {count} errors)"
                            )
                            requeued = await self.db.unblock_source(source_id)
                            self.logger.info(
                                f"   ↩  {requeued} article(s) re-queued for enrichment"
                            )
                            unblocked_count += 1
                        else:
                            ec = result.get('error_code') if result else 'no data'
                            self.logger.debug(
                                f"🚫 [{source_name}] still blocked ({count} errors, {ec})"
                            )

                    except Exception as e:
                        self.logger.debug(f"🔍 Probe error for [{source_name}]: {e}")

                    await asyncio.sleep(PROBE_DELAY)

                self.logger.info(
                    f"🔍 Probe cycle complete — unblocked {unblocked_count}/{len(rows)} source(s). "
                    f"Sleeping {PROBE_CYCLE_INTERVAL}s…"
                )

            except asyncio.CancelledError:
                self.logger.info("🔍 Probe blocked sources cancelled")
                return
            except Exception as e:
                self.logger.error(f"🔍 Probe blocked sources error: {e}", exc_info=True)

            await asyncio.sleep(PROBE_CYCLE_INTERVAL)

    async def backfill_translations(self):
        """
        Continuously translate articles whose is_translated=0 and whose
        detected_language requires translation (per the languages table).

        Each cycle:
          1. Fetch a batch of untranslated articles with a non-null title,
             ordered newest first.
          2. For each article, call translatev1.translate_article() for
             title, description, and content.
          3. If Google returned a translated result, write translated_title /
             translated_description / translated_content and set is_translated=1.
          4. If the text was unchanged (e.g. misdetected language already in
             target language), leave translated_* NULL and is_translated stays 0
             so we skip it on future cycles (mark with is_translated=-1).
          5. Sleep TRANSLATE_DELAY between articles, TRANSLATE_CYCLE_INTERVAL
             between full cycles.
        """
        if not TRANSLATE_ENABLED:
            self.logger.info("⏭️  Translation backfill disabled (TRANSLATE_ENABLED=False)")
            return

        # Import here so the module is loaded once and its lru_cache is shared
        import translatev1 as tv
        tv._load_language_rules.cache_clear()

        # Start both translation subprocesses eagerly so they are warm before
        # any article needs translating.  Both sit idle on their request queues
        # until called.  Google subprocess starts in milliseconds; NLLB takes
        # ~40 s to load the model onto the GPU.
        tv._google.start()
        tv._nllb.start()

        self.logger.info(
            f"🌐 Translation backfill started — batch={TRANSLATE_BATCH_SIZE}, "
            f"delay={TRANSLATE_DELAY}s, cycle={TRANSLATE_CYCLE_INTERVAL}s"
        )

        while not self.shutdown_flag:
            # ── Bulk-skip: mark articles that don't need translation → -1 ────
            # Runs every cycle so new articles inserted since startup are caught.
            # Two cases:
            #   a) detected_language has translate=0 in the languages table (en, pt, …)
            #   b) detected_language is set but references no row in languages at all
            #      (unsupported/unknown language code)
            # Articles with NULL detected_language are left alone — language
            # detection may still run and set a translatable language later.
            try:
                skipped = await self.db.bulk_skip_non_translatable()
                if skipped:
                    self.logger.info(
                        f"🌐 Translation: bulk-skipped {skipped} articles "
                        f"(translate=0 or unsupported language)"
                    )
            except Exception as e:
                self.logger.warning(f"Translation bulk-skip failed (non-critical): {e}")
            try:
                # ── 1. Find articles that need translation ─────────────────
                # Uses the optimised view v_articles_pending_translation which
                # already applies all filters (is_translated=0, title not null/empty,
                # translate=1 or unknown language) and carries the resolved
                # target_language / translator_code from the languages table.
                rows = await self.db.fetch_pending_translation(TRANSLATE_BATCH_SIZE)

                if not rows:
                    self.logger.info(
                        f"✅ Translation backfill: no pending articles — "
                        f"sleeping {TRANSLATE_CYCLE_INTERVAL}s"
                    )
                    await asyncio.sleep(TRANSLATE_CYCLE_INTERVAL)
                    continue

                self.logger.info(
                    f"🌐 Translation backfill: processing {len(rows)} articles..."
                )
                translated_count = 0
                skipped_count = 0

                for row in rows:
                    if self.shutdown_flag:
                        break

                    article_id  = row['id_article']
                    lang        = row['detected_language']  # may be None
                    title       = row['title']       or ''
                    description = row['description'] or ''
                    content     = row['content']     or ''

                    # Translate all three fields; NLLB subprocess used as fallback
                    # when Google fails — fully async, does not block the event loop.
                    (t_title, ok_t), (t_desc, ok_d), (t_cont, ok_c) = \
                        await tv.translate_article_fields_async(
                            title, description, content, lang
                        )

                    any_translated = ok_t or ok_d or ok_c

                    try:
                        values: dict = {
                            'is_translated': 1 if any_translated else -1,
                        }
                        if ok_t:
                            values['translated_title'] = t_title
                        if ok_d:
                            values['translated_description'] = t_desc
                        if ok_c:
                            values['translated_content'] = t_cont
                        await self.db.save_translation(article_id, values)
                        if any_translated:
                            translated_count += 1
                            self.logger.debug(
                                f"🌐 Translated [{lang}]: {title[:60]}"
                            )
                        else:
                            skipped_count += 1
                            self.logger.debug(
                                f"⏭️  No translation needed [{lang}]: {title[:60]}"
                            )
                    except Exception as e:
                        self.logger.error(
                            f"Translation DB write failed for {article_id}: {e}"
                        )

                    await asyncio.sleep(TRANSLATE_DELAY)

                self.logger.info(
                    f"🌐 Translation cycle done — translated={translated_count}, "
                    f"skipped={skipped_count} — sleeping {TRANSLATE_CYCLE_INTERVAL}s"
                )
                await asyncio.sleep(TRANSLATE_CYCLE_INTERVAL)

            except asyncio.CancelledError:
                self.logger.info("🏁 Translation backfill task cancelled")
                return
            except Exception as e:
                self.logger.error(f"Translation backfill unexpected error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _refresh_queue_stats(self, interval: int = 30) -> None:
        """Background task: refresh db.cached_stats every `interval` seconds."""
        while not self.shutdown_flag:
            try:
                stats = await self.db.refresh_stats_cache()
                self.logger.debug(
                    f"📊 Queue stats refreshed — enrich_pending={stats['enrich_pending']}, "
                    f"translate_pending={stats['translate_pending']}"
                )
            except Exception as e:
                self.logger.warning(f"Queue stats refresh failed: {e}")
            await asyncio.sleep(interval)

    async def serve_api(self):
        """Run FastAPI HTTP server (real-time article polling endpoint)."""
        if not API_SERVER_ENABLED:
            self.logger.info("⏭️  API server disabled (API_SERVER_ENABLED=False)")
            return
        if not _FASTAPI_AVAILABLE:
            self.logger.warning("⚠️  FastAPI not available — API server skipped")
            return

        # Narrow types for static analysis — guaranteed non-None past this point
        assert FastAPI is not None
        assert CORSMiddleware is not None
        assert Query is not None
        assert HTTPException is not None
        assert uvicorn is not None

        from sqlalchemy import func as sa_func
        from typing import cast as typing_cast

        api_app = FastAPI(
            title="wxNews API",
            description="Real-time news updates API with timestamp-based queries",
            version="2.0.0",
        )
        api_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        gather = self  # closure reference
        # Local alias so nested async handlers inherit the narrowed type
        _HTTPException = HTTPException

        @api_app.get("/")
        async def root():
            return {
                "name": "wxNews API", "version": "2.0.0", "status": "running",
                "endpoints": {
                    "GET /api/health": "Health check",
                    "GET /api/articles": "Get articles since timestamp",
                    "GET /api/latest_timestamp": "Get latest insertion timestamp",
                    "GET /api/sources": "Get available news sources",
                    "GET /api/stats": "Get collection statistics",
                    },
                    "GET /api/queues": "Queue sizes (enrichment, translation)",
                "database": "connected",
            }

        @api_app.get("/api/articles")
        async def get_articles(
            since: int = Query(..., description="Timestamp in milliseconds"),
            limit: int = Query(100, ge=1, le=API_MAX_ARTICLES),
            sources: Optional[str] = Query(None, description="Comma-separated source IDs"),
        ):
            try:
                current_time_ms = int(time.time() * 1000)
                from sqlalchemy import literal_column as lc
                query = (
                    select(
                        gather.gm_articles.c.id_article,
                        gather.gm_articles.c.id_source,
                        gather.gm_articles.c.author,
                        gather.gm_articles.c.title,
                        gather.gm_articles.c.description,
                        gather.gm_articles.c.url,
                        gather.gm_articles.c.urlToImage,
                        gather.gm_articles.c.publishedAt,
                        gather.gm_articles.c.published_at_gmt,
                        gather.gm_articles.c.inserted_at_ms,
                        gather.gm_articles.c.translated_title,
                        gather.gm_articles.c.translated_description,
                        gather.gm_articles.c.translated_content,
                        gather.gm_articles.c.is_translated,
                    )
                    .where(gather.gm_articles.c.inserted_at_ms > since)
                    .where(gather.gm_articles.c.inserted_at_ms <= current_time_ms)
                    .where(
                        (gather.gm_articles.c.published_at_gmt.is_(None))
                        | (lc("datetime(published_at_gmt)") <= lc("datetime('now')"))
                    )
                )
                if sources:
                    src_list = [s.strip() for s in sources.split(',') if s.strip()]
                    if src_list:
                        query = query.where(gather.gm_articles.c.id_source.in_(src_list))
                query = query.order_by(gather.gm_articles.c.inserted_at_ms.desc()).limit(limit)
                with gather.eng.connect() as conn:
                    rows = conn.execute(query).fetchall()
                articles = [
                    {
                        'id_article': r[0], 'id_source': r[1], 'author': r[2],
                        'title': r[3], 'description': r[4], 'url': r[5],
                        'urlToImage': r[6], 'publishedAt': r[7],
                        'published_at_gmt': r[8], 'inserted_at_ms': r[9],
                        'translated_title': r[10], 'translated_description': r[11],
                        'translated_content': r[12], 'is_translated': r[13],
                    }
                    for r in rows
                ]
                latest_ts = articles[0]['inserted_at_ms'] if articles else since
                return {'success': True, 'count': len(articles), 'since': since,
                        'latest_timestamp': latest_ts, 'articles': articles,
                        'timestamp': int(time.time() * 1000)}
            except Exception as e:
                self.logger.error(f"API /api/articles error: {e}", exc_info=True)
                raise _HTTPException(status_code=500, detail=str(e))

        @api_app.get("/api/latest_timestamp")
        async def get_latest_timestamp():
            try:
                with gather.eng.connect() as conn:
                    row = conn.execute(
                        select(
                            sa_func.max(gather.gm_articles.c.inserted_at_ms).label('latest_ts'),
                            sa_func.count().label('total'),
                        ).where(gather.gm_articles.c.inserted_at_ms.isnot(None))
                    ).fetchone()
                return {'success': True,
                        'latest_timestamp': (row[0] or 0) if row else 0,
                        'total_articles': (row[1] or 0) if row else 0,
                        'timestamp': int(time.time() * 1000)}
            except Exception as e:
                raise _HTTPException(status_code=500, detail=str(e))

        @api_app.get("/api/sources")
        async def get_sources():
            try:
                query = (
                    select(
                        gather.gm_sources.c.id_source,
                        gather.gm_sources.c.name,
                        gather.gm_sources.c.category,
                        gather.gm_sources.c.language,
                        sa_func.count(gather.gm_articles.c.id_article).label('article_count'),
                    )
                    .select_from(
                        gather.gm_sources.outerjoin(
                            gather.gm_articles,
                            gather.gm_sources.c.id_source == gather.gm_articles.c.id_source,
                        )
                    )
                    .group_by(gather.gm_sources.c.id_source)
                    .having(sa_func.count(gather.gm_articles.c.id_article) > 0)
                    .order_by(gather.gm_sources.c.name)
                )
                with gather.eng.connect() as conn:
                    rows = conn.execute(query).fetchall()
                return {'success': True, 'count': len(rows),
                        'sources': [{'id_source': r[0], 'name': r[1],
                                     'category': r[2], 'language': r[3],
                                     'article_count': r[4]} for r in rows]}
            except Exception as e:
                raise _HTTPException(status_code=500, detail=str(e))

        @api_app.get("/api/queues")
        async def get_queues():
            try:
                now_ms = int(time.time() * 1000)

                # Return cached stats — refreshed every 30 s by _refresh_queue_stats()
                s = gather.db.cached_stats
                worker_q  = gather._enrichment_worker.input_queue.qsize()
                in_flight = len(gather._backfill_processing_ids)
                total_articles = s["enriched"] + s["enrich_failed"] + s["enrich_pending"]
                return {
                    "success": True,
                    "timestamp": now_ms,
                    "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ms / 1000)),
                    "stats_age_s": round((now_ms - s["refreshed_at"]) / 1000, 1) if s["refreshed_at"] else None,
                    "articles": {
                        "total": total_articles,
                        "enriched": s["enriched"],
                        "enrich_failed": s["enrich_failed"],
                        "enrich_pending": s["enrich_pending"],
                        "translated": s["translated"],
                        "translate_skipped": s["translate_skipped"],
                    },
                    "enrichment": {
                        "worker_queue": worker_q,
                        "in_flight": in_flight,
                        "pending_db": s["enrich_pending"],
                    },
                    "translation": {
                        "pending_db": s["translate_pending"],
                    },
                }
            except Exception as e:
                raise _HTTPException(status_code=500, detail=str(e))

        @api_app.get("/api/stats")
        async def get_stats():
            try:
                st = await gather.db.fetch_article_stats()
                return {
                    'success': True,
                    'total_articles':    st['total'],
                    'articles_last_24h': st['last_24h'],
                    'articles_last_hour':st['last_hour'],
                    'total_sources':     st['total_sources'],
                    'timestamp':         st['timestamp'],
                }
            except Exception as e:
                raise _HTTPException(status_code=500, detail=str(e))

        @api_app.get("/api/monitor")
        async def get_monitor():
            """Full stats for watch_translations and other dashboards."""
            try:
                s    = gather.db.cached_stats
                total = s['enriched'] + s['enrich_failed'] + s['enrich_pending']
                pending_by_lang = await gather.db.fetch_pending_by_language()
                return {
                    'success':           True,
                    'total':             total,
                    'enriched':          s['enriched'],
                    'not_enriched':      s['enrich_pending'],
                    'enrich_failed':     s['enrich_failed'],
                    'enrich_pending':    s['enrich_pending'],
                    'translated':        s['translated'],
                    'translate_pending': s['translate_pending'],
                    'pending_by_language': pending_by_lang,
                }
            except Exception as e:
                raise _HTTPException(status_code=500, detail=str(e))

        self.logger.info(f"🌐 API server starting on http://{API_HOST}:{API_PORT}")
        config_uvicorn = uvicorn.Config(
            api_app,
            host=API_HOST,
            port=API_PORT,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config_uvicorn)
        await server.serve()

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
    import argparse
    parser = argparse.ArgumentParser(description='wxAsyncNewsGather news collector')
    parser.add_argument('--debug', action='store_true', help='Enable DEBUG logging (shows translator input/output)')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO

    root = logging.getLogger()
    root.setLevel(log_level)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # stdout handler (captured by journald when running under systemd)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # File handler — always writes to collector.log in the working directory
    import os as _os
    _log_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'collector.log')
    file_handler = logging.handlers.RotatingFileHandler(
        _log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    
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

        # Cancel all collector tasks — asyncio.to_thread() tasks are not
        # directly cancellable mid-thread, but cancelling the wrapping Task
        # makes gather() return promptly once current thread calls complete.
        for task in collector_tasks:
            if not task.done():
                task.cancel()

        # Schedule a hard exit after 8 s in case threads are still running.
        # This fires before systemd's TimeoutStopSec=10 sends SIGKILL.
        def _force_exit():
            import os, sys
            app.logger.warning("⚠️  Force-exiting after timeout (threads still running)")
            sys.stdout.flush()
            os._exit(0)
        import threading
        threading.Timer(8.0, _force_exit).start()

        app.logger.info("✅ Shutdown signal processed")
    
    # Register signal handlers (asyncio-compatible)
    loop.add_signal_handler(signal.SIGINT, handle_shutdown_signal)   # Ctrl+C
    loop.add_signal_handler(signal.SIGTERM, handle_shutdown_signal)  # systemd stop
    
    # Run all three collectors in parallel
    async def run_all_collectors():
        await app.open_async_db()
        app.logger.info("🚀 Starting all news collectors in parallel...")
        app.logger.info(f"   • NewsAPI: every {NEWSAPI_CYCLE_INTERVAL}s ({NEWSAPI_CYCLE_INTERVAL//60} min)")
        app.logger.info(f"   • RSS Feeds: every {RSS_CYCLE_INTERVAL}s ({RSS_CYCLE_INTERVAL//60} min)")
        app.logger.info(f"   • MediaStack: every {MEDIASTACK_CYCLE_INTERVAL}s ({MEDIASTACK_CYCLE_INTERVAL//60} min)")
        app.logger.info(f"   • Backfill content: cffi(batch={CFFI_BATCH_SIZE}, concur={CFFI_CONCURRENCY}, t={CFFI_TIMEOUT}s) "
                         f"| requests(batch={REQUESTS_BATCH_SIZE}, concur={REQUESTS_CONCURRENCY}, t={REQUESTS_TIMEOUT}s) "
                         f"| playwright(batch={PLAYWRIGHT_BATCH_SIZE}, concur={PLAYWRIGHT_CONCURRENCY}, t={PLAYWRIGHT_TIMEOUT}s)")
        app.logger.info(f"   • Translate: every {TRANSLATE_CYCLE_INTERVAL}s ({TRANSLATE_CYCLE_INTERVAL//60} min), batch={TRANSLATE_BATCH_SIZE}")
        app.logger.info(f"   • Probe blocked sources: every {PROBE_CYCLE_INTERVAL}s ({PROBE_CYCLE_INTERVAL//60} min)")

        # Create tasks for all collectors + translation + API server
        tasks = [
            loop.create_task(app.collect_newsapi()),
            loop.create_task(app.collect_rss_feeds()),
            loop.create_task(app.collect_mediastack()),
            loop.create_task(app._cffi_worker.run()),
            loop.create_task(app._requests_worker.run()),
            loop.create_task(app._playwright_worker.run()),
            loop.create_task(app.backfill_content()),
            loop.create_task(app.backfill_translations()),
            loop.create_task(app.probe_blocked_sources()),
            loop.create_task(app._refresh_queue_stats()),
            loop.create_task(app.serve_api()),
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
            if app.db:
                await app.db.close()
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
