#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Article content fetcher — IPC-based orchestrator.

Each HTTP backend runs as a persistent subprocess and communicates via
multiprocessing Queues (same pattern as google_worker / nllb_worker).

Workers
-------
  cffi_worker.py       — curl_cffi with Chrome TLS fingerprint (primary)
  requests_worker.py   — stdlib requests with browser headers (primary fallback)
  playwright_worker.py — headless Chromium for JS-rendered pages (final fallback)

Orchestration logic (fetch())
------------------------------
  1. Primary: cffi (if available) else requests
  2. Playwright fallback when:
       a. primary was bot-blocked (403/406)
       b. primary had a temporary error (network/timeout)
       c. primary succeeded but returned a JS skeleton with no real content
  3. Parse HTML  →  extract author/time/description/content

Public API
----------
  fetch_article_content(url, timeout=10)  →  dict
  ArticleContentFetcher(timeout).fetch(url)  →  dict

  result dict keys:
    author, published_time, description, content,
    success (bool), error_code, error_type ('permanent'|'temporary'|None),
    sanitized_url
"""

import asyncio
import logging
import multiprocessing
import re
import threading
import uuid

from bs4 import BeautifulSoup

import cffi_worker
import requests_worker
import playwright_worker

logger = logging.getLogger(__name__)

# ── Error-type constants ──────────────────────────────────────────────────────
ERROR_PERMANENT = 'permanent'
ERROR_TEMPORARY = 'temporary'

_BOT_BLOCKED_CODES = frozenset({403, 406})


# ---------------------------------------------------------------------------
# Generic subprocess fetcher (shared by all three backends)
# ---------------------------------------------------------------------------

class _ProcessFetcher:
    """
    Subprocess wrapper for a fetcher backend worker.

    Subclasses implement ``_make_process()`` only.  All queue management,
    pump thread, lifecycle, and sync/async call interface live here.

    Worker protocol
    ---------------
    request:  ``(req_id: str, url: str, timeout: int)``
            | ``None``   ← shutdown sentinel
    response: ``(req_id: str, result: dict)``
    """

    _PROCESS_NAME = 'fetcher'
    _PUMP_NAME    = 'fetcher-pump'

    def __init__(self, pool_size: int = 1) -> None:
        self._pool_size    = pool_size
        self._processes:    list[multiprocessing.Process] = []
        self._req_q:        'multiprocessing.Queue | None' = None
        self._resp_q:       'multiprocessing.Queue | None' = None
        self._async_pending: dict[str, 'asyncio.Future'] = {}
        self._sync_pending:  dict[str, list]             = {}
        self._lock         = threading.Lock()
        self._pump_thread: threading.Thread | None = None
        self._loop:        asyncio.AbstractEventLoop | None = None
        self._started      = False
        self._shutdown     = threading.Event()

    def _make_process(self, ctx, req_q, resp_q) -> multiprocessing.Process:
        raise NotImplementedError

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._ensure_started()

    def _ensure_started(self) -> None:
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            ctx          = multiprocessing.get_context('spawn')
            self._req_q  = ctx.Queue()
            self._resp_q = ctx.Queue()
            for i in range(self._pool_size):
                p = self._make_process(ctx, self._req_q, self._resp_q)
                p.start()
                self._processes.append(p)
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = None
            self._pump_thread = threading.Thread(
                target=self._pump_responses,
                daemon=True,
                name=self._PUMP_NAME,
            )
            self._pump_thread.start()
            self._started = True
            import atexit
            atexit.register(self.shutdown)

    def _pump_responses(self) -> None:
        assert self._resp_q is not None
        while not self._shutdown.is_set():
            try:
                item = self._resp_q.get(timeout=0.5)
            except Exception:
                continue
            req_id, result = item
            with self._lock:
                fut       = self._async_pending.pop(req_id, None)
                sync_slot = self._sync_pending.get(req_id)
            if fut is not None and self._loop is not None:
                self._loop.call_soon_threadsafe(
                    lambda f=fut, r=result: f.set_result(r) if not f.done() else None
                )
            elif sync_slot is not None:
                sync_slot[1] = result
                sync_slot[0].set()

    def shutdown(self) -> None:
        if not self._started or self._shutdown.is_set():
            return
        self._shutdown.set()
        if self._req_q is not None:
            try:
                # One sentinel per worker process so each wakes up and exits
                for _ in self._processes:
                    self._req_q.put_nowait(None)
            except Exception:
                pass
        for p in self._processes:
            p.join(timeout=10)
            if p.is_alive():
                p.terminate()
                p.join(timeout=3)
        if self._pump_thread is not None:
            self._pump_thread.join(timeout=3)
        with self._lock:
            if self._loop is not None:
                for fut in self._async_pending.values():
                    if not fut.done():
                        self._loop.call_soon_threadsafe(
                            fut.set_result,
                            {'html': None, 'success': False,
                             'error_code': 'SHUTDOWN', 'error_type': ERROR_TEMPORARY},
                        )
            for slot in self._sync_pending.values():
                slot[1] = {'html': None, 'success': False,
                           'error_code': 'SHUTDOWN', 'error_type': ERROR_TEMPORARY}
                slot[0].set()
            self._async_pending.clear()
            self._sync_pending.clear()

    # ── call interface ────────────────────────────────────────────────────────

    def fetch_sync(self, url: str, timeout: int = 10,
                   options: dict | None = None) -> dict:
        """Blocking fetch — safe to call from any thread."""
        if self._shutdown.is_set():
            return {'html': None, 'success': False,
                    'error_code': 'SHUTDOWN', 'error_type': ERROR_TEMPORARY}
        self._ensure_started()
        req_id = str(uuid.uuid4())
        event  = threading.Event()
        slot: list = [event, None]
        with self._lock:
            self._sync_pending[req_id] = slot
        assert self._req_q is not None
        self._req_q.put((req_id, url, timeout, options or {}))
        event.wait(timeout=timeout + 30)     # subprocess timeout + grace period
        with self._lock:
            self._sync_pending.pop(req_id, None)
        if slot[1] is None:
            return {'html': None, 'success': False,
                    'error_code': 'TIMEOUT', 'error_type': ERROR_TEMPORARY}
        return slot[1]

    async def fetch_async(self, url: str, timeout: int = 10,
                          options: dict | None = None) -> dict:
        """Non-blocking fetch for use inside an asyncio event loop."""
        if self._shutdown.is_set():
            return {'html': None, 'success': False,
                    'error_code': 'SHUTDOWN', 'error_type': ERROR_TEMPORARY}
        self._ensure_started()
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        req_id = str(uuid.uuid4())
        fut: asyncio.Future = loop.create_future()
        with self._lock:
            self._async_pending[req_id] = fut
        assert self._req_q is not None
        self._req_q.put((req_id, url, timeout, options or {}))
        return await asyncio.wait_for(fut, timeout=timeout + 30)


# ---------------------------------------------------------------------------
# Concrete backends
# ---------------------------------------------------------------------------

class _CffiFetcher(_ProcessFetcher):
    _PROCESS_NAME = 'cffi-fetch'
    _PUMP_NAME    = 'cffi-pump'

    def _make_process(self, ctx, req_q, resp_q):
        return ctx.Process(
            target=cffi_worker.worker,
            args=(req_q, resp_q),
            daemon=True,
            name=self._PROCESS_NAME,
        )


class _RequestsFetcher(_ProcessFetcher):
    _PROCESS_NAME = 'requests-fetch'
    _PUMP_NAME    = 'requests-pump'

    def _make_process(self, ctx, req_q, resp_q):
        return ctx.Process(
            target=requests_worker.worker,
            args=(req_q, resp_q),
            daemon=True,
            name=self._PROCESS_NAME,
        )


class _PlaywrightFetcher(_ProcessFetcher):
    _PROCESS_NAME = 'playwright-fetch'
    _PUMP_NAME    = 'playwright-pump'

    def _make_process(self, ctx, req_q, resp_q):
        return ctx.Process(
            target=playwright_worker.worker,
            args=(req_q, resp_q),
            daemon=True,
            name=self._PROCESS_NAME,
        )


# Module-level singletons — started lazily on first use.
# pool_size controls how many worker processes run per backend:
#   cffi      — fast HTTP/TLS, I/O-bound → 4 workers
#   requests  — stdlib fallback           → 2 workers
#   playwright — headless Chrome, RAM-heavy → 2 workers
_cffi       = _CffiFetcher(pool_size=4)
_requests   = _RequestsFetcher(pool_size=2)
_playwright = _PlaywrightFetcher(pool_size=2)


def start_all() -> None:
    """Eagerly start all fetcher subprocesses (call at service startup)."""
    _cffi.start()
    _requests.start()
    _playwright.start()


def shutdown_all() -> None:
    """Gracefully stop all fetcher subprocesses."""
    _cffi.shutdown()
    _requests.shutdown()
    _playwright.shutdown()


# ---------------------------------------------------------------------------
# HTML parsing helpers (run in the orchestrator process, not in workers)
# ---------------------------------------------------------------------------

def _html_has_content(html: str | None) -> bool:
    """Quick heuristic: ≥2 real paragraphs → page has readable content."""
    if not html:
        return False
    soup = BeautifulSoup(html[:15000], 'html.parser')
    paras = [p.get_text().strip() for p in soup.find_all('p')
             if len(p.get_text().strip()) > 50]
    return len(paras) >= 2


def _parse_html(html: str, url: str = '') -> 'BeautifulSoup | None':
    for parser in ('lxml', 'html.parser'):
        try:
            return BeautifulSoup(html, parser)
        except Exception as e:
            if parser == 'html.parser':
                logger.debug("All HTML parsers failed for %s: %s", url, e)
    return None


def _extract_author(soup) -> str | None:
    for meta_attr in [
        {'property': 'article:author'},
        {'name': 'author'},
        {'property': 'og:article:author'},
    ]:
        tag = soup.find('meta', attrs=meta_attr)
        if tag and tag.get('content'):
            return tag.get('content').strip()
    author_tag = soup.find(attrs={'itemprop': 'author'})
    if author_tag:
        name_tag = author_tag.find(attrs={'itemprop': 'name'})
        if name_tag:
            return name_tag.get_text().strip()
        return author_tag.get_text().strip()
    for class_name in ['author', 'article-author', 'byline', 'author-name']:
        tag = soup.find(class_=re.compile(class_name, re.I))
        if tag:
            text = re.sub(r'^by\s+', '', tag.get_text().strip(), flags=re.I)
            if text and len(text) < 100:
                return text
    return None


def _extract_time(soup) -> str | None:
    for meta_attr in [
        {'property': 'article:published_time'},
        {'name': 'publishdate'},
        {'property': 'og:published_time'},
        {'name': 'date'},
    ]:
        tag = soup.find('meta', attrs=meta_attr)
        if tag and tag.get('content'):
            return tag.get('content').strip()
    time_tag = soup.find('time')
    if time_tag:
        return time_tag.get('datetime') or time_tag.get_text().strip()
    time_tag = soup.find(attrs={'itemprop': 'datePublished'})
    if time_tag:
        return time_tag.get('content') or time_tag.get_text().strip()
    return None


def _extract_description(soup) -> str | None:
    og = soup.find('meta', property='og:description')
    if og and og.get('content'):
        return og.get('content').strip()
    meta = soup.find('meta', attrs={'name': 'description'})
    if meta and meta.get('content'):
        return meta.get('content').strip()
    for class_name in ['article-summary', 'article-lead', 'lead', 'summary', 'article-description']:
        tag = soup.find(class_=re.compile(class_name, re.I))
        if tag:
            text = tag.get_text().strip()
            if len(text) > 20:
                return text
    return None


def _extract_content(soup) -> str | None:
    paragraphs = []
    for selector in [
        {'class_': re.compile(r'article-content|article-body|entry-content|post-content', re.I)},
        {'attrs': {'itemprop': 'articleBody'}},
        {'name': 'article'},
    ]:
        container = soup.find(**selector)
        if container:
            p_tags = container.find_all('p', recursive=True)
            paragraphs = [p.get_text().strip() for p in p_tags
                          if len(p.get_text().strip()) > 30]
            if paragraphs:
                break
    if not paragraphs:
        paragraphs = [p.get_text().strip() for p in soup.find_all('p')
                      if len(p.get_text().strip()) > 50]
    if paragraphs:
        return '\n\n'.join(paragraphs)[:50000]
    return None


_PAYWALL_PHRASES = (
    'subscribe now to read',
    'subscribe to read',
    'subscribe to continue',
    'subscribe for full access',
    'you can save this article by registering',
    'sign in to read',
    'sign up to read',
    'create a free account to read',
    'create an account to read',
    'log in to read',
    'login to read',
    'to read this article',
    'to continue reading',
    'unlock this article',
    'already a subscriber',
    'become a subscriber',
    'purchase a subscription',
)


def _is_paywall_content(text: str | None) -> bool:
    """Return True if the text appears to be a paywall / subscription gate."""
    if not text:
        return False
    sample = text[:600].lower()
    return any(phrase in sample for phrase in _PAYWALL_PHRASES)


def _soup_to_fields(soup) -> dict:
    content = _extract_content(soup)
    description = _extract_description(soup)
    paywall = _is_paywall_content(content) or _is_paywall_content(description)
    if paywall:
        logger.debug("[fetch] paywall content detected — discarding")
        content = None
        description = None
    return {
        'author':         _extract_author(soup),
        'published_time': _extract_time(soup),
        'description':    description,
        'content':        content,
        '_paywall':       paywall,
    }


# ---------------------------------------------------------------------------
# URL sanitization (unchanged — pure string logic, orchestrator only)
# ---------------------------------------------------------------------------

def _sanitize_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return url
    url = url.strip()
    for param in ('?u=', '&u=', '?url=', '&url='):
        if param in url:
            inner = url.split(param, 1)[1].split('&', 1)[0]
            inner = re.sub(r'^(https?:/)(?!/)', r'\1/', inner)
            if inner.startswith(('http://', 'https://')):
                url = inner
            break
    if '*http://' in url or '*https://' in url:
        if '*https://' in url:
            url = 'https://' + url.split('*https://', 1)[1]
        elif '*http://' in url:
            url = 'http://' + url.split('*http://', 1)[1]
    if '://' in url:
        protocol, rest = url.split('://', 1)
        rest = re.sub(r'/+', '/', rest)
        url = f'{protocol}://{rest}'
    return url


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class ArticleContentFetcher:
    """
    Orchestrator: picks the right backend(s), parses HTML, returns fields.

    All heavy work (HTTP, browser) happens in isolated worker subprocesses.
    """

    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout

    # Expose for backwards compatibility (used in wxAsyncNewsGather parsing helpers)
    @staticmethod
    def sanitize_url(url: str) -> str:
        return _sanitize_url(url)

    async def fetch_async(self, url: str) -> dict:
        """
        Fully async fetch — no threads, no run_in_executor for HTTP.
        Uses fetch_async() on each backend (IPC Future resolved by pump thread).
        HTML parsing (lxml) runs in the default executor to avoid CPU blocking.
        """
        result: dict = {
            'author': None, 'published_time': None,
            'description': None, 'content': None,
            'success': False, 'error_code': None,
            'error_type': None, 'sanitized_url': None,
        }

        sanitized = _sanitize_url(url)
        if sanitized != url:
            logger.info("URL sanitized: %s -> %s", url, sanitized)
            result['sanitized_url'] = sanitized
        if not sanitized or not sanitized.startswith(('http://', 'https://')):
            logger.warning("Invalid URL: %s", url)
            result['error_code'] = 'INVALID_URL'
            result['error_type'] = ERROR_PERMANENT
            return result

        # Primary backend
        primary = await _cffi.fetch_async(sanitized, self.timeout)
        if not primary['success'] and primary['error_code'] == 'UNAVAILABLE':
            primary = await _requests.fetch_async(sanitized, self.timeout)

        best = primary

        # Playwright fallback
        try_pw = (
            primary['error_code'] in _BOT_BLOCKED_CODES
            or (not primary['success'] and primary['error_type'] == ERROR_TEMPORARY)
            or (primary['success'] and not _html_has_content(primary.get('html')))
        )
        if try_pw:
            logger.debug("[fetch-async] playwright fallback (primary=%s): %s",
                         primary['error_code'] or 'no content', sanitized)
            pw = await _playwright.fetch_async(sanitized, self.timeout)
            if pw['success']:
                best = pw
            elif not primary['success'] and pw['error_type'] == ERROR_PERMANENT:
                best = pw

        # Parse HTML in executor (lxml is CPU-bound C extension)
        html = best.get('html')
        if best['success'] and html:
            loop = asyncio.get_running_loop()
            soup = await loop.run_in_executor(None, _parse_html, html, sanitized)
            if soup:
                fields = _soup_to_fields(soup)
                paywall_detected = fields.pop('_paywall', False)
                result.update(fields)
                result['success'] = True
                logger.debug("[fetch-async] OK %s", sanitized)

                if paywall_detected:
                    logger.debug("[fetch-async] nojs retry after paywall: %s", sanitized)
                    nojs = await _playwright.fetch_async(
                        sanitized, self.timeout, options={'nojs': True}
                    )
                    if nojs.get('success') and nojs.get('html'):
                        nojs_soup = await loop.run_in_executor(
                            None, _parse_html, nojs['html'], sanitized
                        )
                        if nojs_soup:
                            nojs_fields = _soup_to_fields(nojs_soup)
                            nojs_fields.pop('_paywall', None)
                            if nojs_fields.get('content'):
                                result.update(nojs_fields)
                                logger.debug("[fetch-async] nojs content retrieved: %s", sanitized)
            else:
                result['error_code'] = 'PARSE_ERROR'
                result['error_type'] = ERROR_TEMPORARY
        else:
            result['error_code'] = best['error_code']
            result['error_type'] = best['error_type']
            logger.debug("[fetch-async] failed (%s/%s): %s",
                         best['error_code'], best['error_type'], sanitized)

        return result

    def fetch(self, url: str) -> dict:
        """
        Fetch article content from *url*.

        Returns dict with:
          author, published_time, description, content,
          success, error_code, error_type, sanitized_url
        """
        result: dict = {
            'author': None, 'published_time': None,
            'description': None, 'content': None,
            'success': False, 'error_code': None,
            'error_type': None, 'sanitized_url': None,
        }

        # Sanitize + validate
        sanitized = _sanitize_url(url)
        if sanitized != url:
            logger.info("URL sanitized: %s -> %s", url, sanitized)
            result['sanitized_url'] = sanitized
        if not sanitized or not sanitized.startswith(('http://', 'https://')):
            logger.warning("Invalid URL: %s", url)
            result['error_code'] = 'INVALID_URL'
            result['error_type'] = ERROR_PERMANENT
            return result

        # Primary backend: cffi → requests
        primary = _cffi.fetch_sync(sanitized, self.timeout)
        if not primary['success'] and primary['error_code'] == 'UNAVAILABLE':
            primary = _requests.fetch_sync(sanitized, self.timeout)

        best = primary

        # Playwright fallback
        try_pw = (
            primary['error_code'] in _BOT_BLOCKED_CODES
            or (not primary['success'] and primary['error_type'] == ERROR_TEMPORARY)
            or (primary['success'] and not _html_has_content(primary.get('html')))
        )
        if try_pw:
            logger.debug("[fetch] playwright fallback (primary=%s): %s",
                         primary['error_code'] or 'no content', sanitized)
            pw = _playwright.fetch_sync(sanitized, self.timeout)
            if pw['success']:
                best = pw
            elif not primary['success'] and pw['error_type'] == ERROR_PERMANENT:
                best = pw

        # Parse HTML
        html = best.get('html')
        if best['success'] and html:
            soup = _parse_html(html, sanitized)
            if soup:
                fields = _soup_to_fields(soup)
                paywall_detected = fields.pop('_paywall', False)
                result.update(fields)
                result['success'] = True
                logger.debug("[fetch] OK %s", sanitized)

                # Paywall gate detected — retry with JavaScript disabled.
                # Many soft paywalls are client-side only: the server returns
                # the full article in SSR HTML; JS then hides it. With nojs,
                # we receive the raw SSR and extract the real content.
                if paywall_detected:
                    logger.debug("[fetch] nojs retry after paywall: %s", sanitized)
                    nojs = _playwright.fetch_sync(
                        sanitized, self.timeout, options={'nojs': True}
                    )
                    if nojs.get('success') and nojs.get('html'):
                        nojs_soup = _parse_html(nojs['html'], sanitized)
                        if nojs_soup:
                            nojs_fields = _soup_to_fields(nojs_soup)
                            nojs_fields.pop('_paywall', None)
                            if nojs_fields.get('content'):
                                result.update(nojs_fields)
                                logger.debug("[fetch] nojs content retrieved: %s", sanitized)
            else:
                result['error_code'] = 'PARSE_ERROR'
                result['error_type'] = ERROR_TEMPORARY
        else:
            result['error_code'] = best['error_code']
            result['error_type'] = best['error_type']
            logger.debug("[fetch] failed (%s/%s): %s",
                         best['error_code'], best['error_type'], sanitized)

        return result


# ---------------------------------------------------------------------------
# Public convenience function
# ---------------------------------------------------------------------------

def fetch_article_content(url: str, timeout: int = 10) -> dict:
    """Fetch article content (sync). Returns same dict as ArticleContentFetcher.fetch()."""
    return ArticleContentFetcher(timeout).fetch(url)


async def fetch_article_content_async(url: str, timeout: int = 10) -> dict:
    """Fetch article content (async). No threads — uses IPC futures directly.
    Drop-in async replacement for fetch_article_content()."""
    return await ArticleContentFetcher(timeout).fetch_async(url)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.DEBUG)
    test_url = sys.argv[1] if len(sys.argv) > 1 else \
        'https://www.reuters.com/world/'
    print('=' * 80)
    print(f'Testing: {test_url}')
    print('=' * 80)
    r = fetch_article_content(test_url)
    print(f"\n✓ success:     {r['success']}")
    print(f"✓ error_code:  {r['error_code']} ({r['error_type']})")
    print(f"✓ author:      {r['author']}")
    print(f"✓ published:   {r['published_time']}")
    print(f"✓ description: {(r['description'] or '')[:100]}")
    print(f"✓ content:     {(r['content'] or '')[:200]}")
