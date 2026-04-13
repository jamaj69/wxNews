"""
enrichment_worker.py — Async parallel article-content enrichment service.

Usage
-----
Create one EnrichmentWorker per application, start it as a background task,
then enqueue article dicts and consume results:

    worker = EnrichmentWorker()
    asyncio.create_task(worker.run())

    # Producer side
    await worker.enqueue(article_dict)

    # Consumer side — returns (article_dict, enriched: bool)
    article_dict, enriched = await worker.output_queue.get()

Configuration (via environment / .env)
---------------------------------------
ENRICH_CONCURRENCY   max parallel fetch tasks          (default: 32)
ENRICH_TIMEOUT       per-article fetch timeout (secs)  (default: 10)

The worker never writes to the database; the caller is responsible for
persisting any fields that were updated in article_dict.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from decouple import config

from article_fetcher import (
    fetch_article_content,
    fetch_article_content_async,
    fetch_cffi_only_async,
    fetch_requests_only_async,
    fetch_playwright_only_async,
)
from html_utils import sanitize_html_content, extract_and_remove_first_image

# Maps backend name → single-backend fetch function
_BACKEND_FETCH = {
    'cffi':       fetch_cffi_only_async,
    'requests':   fetch_requests_only_async,
    'playwright': fetch_playwright_only_async,
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENRICH_CONCURRENCY: int = int(config('ENRICH_CONCURRENCY', default=32))
ENRICH_TIMEOUT: int = int(config('ENRICH_TIMEOUT', default=20))

# Consecutive HTTP errors before a source is considered blocked in-memory.
# The authoritative threshold lives in wxAsyncNewsGather._increment_blocked_count;
# this local threshold only guards the worker's own skip logic.
_BLOCKED_THRESHOLD: int = 3

# Consecutive *timeouts* before a domain is skipped for the rest of the session.
# Timeouts are transient (server load, slow connection) so the threshold is
# intentionally higher than _BLOCKED_THRESHOLD.  No DB write is made — the
# block is in-memory only and resets on service restart.
_TIMEOUT_THRESHOLD: int = 5

# HTTP error codes that indicate a source should be (eventually) blocked.
# Only PERMANENT errors count — 500/503 are temporary server-side outages
# and must NOT push a domain toward a permanent block.
_BLOCKING_ERROR_CODES = {401, 402, 403, 406, 410}

ArticleDict = Dict[str, Any]


def _url_domain(url: str) -> str:
    """Return hostname from URL without 'www.' prefix, e.g. 'seekingalpha.com'."""
    try:
        host = urlparse(url).hostname or ''
        return host.removeprefix('www.')
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# EnrichmentWorker
# ---------------------------------------------------------------------------

class EnrichmentWorker:
    """
    Async queue-based parallel article enrichment service.

    * Receives article dicts on ``input_queue``.
    * Enriches up to ``concurrency`` articles concurrently.
    * Puts ``(article_dict, enriched: bool)`` tuples on ``output_queue``.
    * Tracks per-source error counts in memory; skips sources that have
      reached the block threshold since the worker started.

    The caller is responsible for DB writes and for passing ``source_blocked``
      callbacks if persistent tracking is desired (see ``on_source_error``).
    """

    def __init__(
        self,
        concurrency: int = ENRICH_CONCURRENCY,
        timeout: int = ENRICH_TIMEOUT,
        backend: str = 'auto',
    ) -> None:
        self.concurrency = concurrency
        self.timeout = timeout
        # 'auto' uses the full cffi→requests→playwright chain (legacy)
        # 'cffi' | 'requests' | 'playwright' use a single backend only
        self.backend = backend
        self._fetch_fn = _BACKEND_FETCH.get(backend)  # None → auto chain

        self.input_queue: asyncio.Queue[Optional[ArticleDict]] = asyncio.Queue()
        self.output_queue: asyncio.Queue[tuple[ArticleDict, bool]] = asyncio.Queue()

        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(concurrency)

        # domain → consecutive error count (in-memory only).
        # Keyed by URL *domain* (not source_id) so aggregator feeds are never
        # blocked just because some articles inside them point to paywalled sites.
        self._error_counts: dict[str, int] = {}

        # domain → consecutive timeout count (in-memory only, session-scoped).
        # Separate from _error_counts so HTTP errors and timeouts don't mix.
        self._timeout_counts: dict[str, int] = {}

        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(self, article: ArticleDict) -> None:
        """Add an article dict to the enrichment queue."""
        await self.input_queue.put(article)

    async def shutdown(self) -> None:
        """Signal the worker loop to exit after draining in-flight tasks."""
        await self.input_queue.put(None)  # sentinel

    async def run(self) -> None:
        """
        Main loop.  Drains input_queue and dispatches enrichment tasks up to
        *concurrency* at a time.  Exits on ``None`` sentinel or cancellation.
        """
        self.logger.info(
            f"🚀 EnrichmentWorker started — backend={self.backend}, "
            f"concurrency={self.concurrency}, timeout={self.timeout}s"
        )
        pending: set[asyncio.Task] = set()

        try:
            while True:
                article = await self.input_queue.get()
                if article is None:          # shutdown sentinel
                    break
                task = asyncio.create_task(self._enrich_one(article))
                pending.add(task)
                task.add_done_callback(pending.discard)

            # Wait for all in-flight tasks to finish
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            self.logger.info("🏁 EnrichmentWorker cancelled")
            raise
        finally:
            self.logger.info("🏁 EnrichmentWorker stopped")

    async def enrich_direct(self, article: ArticleDict) -> bool:
        """
        Enrich *article* directly without going through the input/output queues.

        Intended for use with PipelineStage workers, where the stage's
        ``max_workers`` provides concurrency control instead of the internal
        semaphore.  Mutates *article* in-place; sets ``_error_code`` and
        ``_blocked_domain`` keys on permanent fetch failures.

        Returns True if at least one field was updated.
        """
        return await self._do_enrich(article)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _enrich_one(self, article: ArticleDict) -> None:
        """Acquire semaphore slot, enrich, then push result to output_queue."""
        async with self._semaphore:
            enriched = await self._do_enrich(article)
            await self.output_queue.put((article, enriched))

    async def _do_enrich(self, article: ArticleDict) -> bool:
        """
        Core enrichment logic (extracted from
        ``wxAsyncNewsGather.enrich_article_content``).

        Returns True if at least one field was updated.
        """
        source_id: str = str(article.get('id_source') or '')
        source_name: str = str(article.get('source_name') or source_id or '')
        url: str = (article.get('url') or '').strip()

        has_author = (article.get('author') or '').strip()
        # Strip HTML tags to get plain-text length — avoids treating
        # stub HTML like HN's "<a href=...>Comments</a>" as real content.
        _desc_plain = re.sub(r'<[^>]+>', '', article.get('description') or '').strip()
        has_description = len(_desc_plain) >= 80
        has_content = bool((article.get('content') or '').strip())

        # Already complete — nothing to do
        if has_author and has_description and has_content:
            return False

        if not url:
            return False

        # Skip if this article's *URL domain* has hit the in-memory error threshold.
        # Use domain (not source_id) so only paywalled domains are skipped, not
        # the entire aggregator feed that may contain articles from many domains.
        domain = _url_domain(url)
        track_key = domain or source_id
        if track_key and self._error_counts.get(track_key, 0) >= _BLOCKED_THRESHOLD:
            self.logger.debug(
                f"⏭️  [{source_name}] Skipping — domain '{domain or source_id}' blocked in-memory"
            )
            return False

        try:
            self.logger.debug(
                f"🔍 [{source_name}] Fetching missing content …"
            )
            # Use single-backend function if backend is set, else full auto chain
            if self._fetch_fn is not None:
                result: Optional[dict] = await self._fetch_fn(url, self.timeout)
            else:
                result = await fetch_article_content_async(url, self.timeout)

            # Track blocking errors in-memory and surface to caller.
            # Store by domain so _backfill_consumer can persist the domain block.
            if result and result.get('error_code') in _BLOCKING_ERROR_CODES:
                self._record_error(track_key, source_name, result['error_code'])
                article['_error_code']      = result['error_code']
                article['_blocked_domain']  = domain  # for DB-level persistence

            if not (result and result.get('success')):
                self.logger.debug(
                    f"⚠️  [{source_name}] Fetch returned no data"
                )
                return False

            updated: list[str] = []

            # --- author ---
            if not has_author and result.get('author'):
                article['author'] = result['author'][:200]
                updated.append('author')

            # --- description (sanitize HTML) ---
            if not has_description and result.get('description'):
                clean = sanitize_html_content(result['description'])
                if clean and re.sub(r'<[^>]+>', '', clean).strip():
                    article['description'] = clean
                    updated.append('description')

            # --- content (sanitize HTML) ---
            if not has_content and result.get('content'):
                clean = sanitize_html_content(result['content'])
                if clean and clean.strip():
                    article['content'] = clean
                    updated.append('content')

            # --- urlToImage — extract from description, remove duplicate ---
            if not article.get('urlToImage') and article.get('description'):
                img_url, clean_desc = extract_and_remove_first_image(
                    article['description']
                )
                if img_url:
                    article['urlToImage'] = img_url
                    article['description'] = clean_desc
                    updated.append('urlToImage')

            # --- publishedAt ---
            if not article.get('publishedAt') and result.get('published_time'):
                article['publishedAt'] = result['published_time']
                updated.append('publishedAt')

            if updated:
                # Successful fetch — reset consecutive timeout counter so a
                # site that was slow isn't stuck in-memory-blocked this session.
                if track_key:
                    self._timeout_counts.pop(track_key, None)
                self.logger.debug(
                    f"✅ [{source_name}] Enriched: {', '.join(updated)}"
                )
                return True

            self.logger.debug(
                f"⚠️  [{source_name}] Fetch OK but no new fields found"
            )
            return False

        except asyncio.TimeoutError:
            # Timeout is transient — tracked separately so sites that are
            # consistently unavailable get skipped for the rest of the session
            # without writing a permanent DB block.
            self._record_timeout(track_key, source_name)
            return False

        except Exception as exc:
            error_msg = str(exc)
            # Detect HTTP error codes embedded in exception messages
            if any(
                code in error_msg
                for code in ['402', 'Payment Required', '403', 'Forbidden',
                             '406', 'Not Acceptable', '410', 'Gone']
            ):
                code_map = {
                    '402': 402, 'Payment Required': 402,
                    '403': 403, 'Forbidden': 403,
                    '406': 406, 'Not Acceptable': 406,
                    '410': 410, 'Gone': 410,
                }
                error_code = 403
                for key, val in code_map.items():
                    if key in error_msg:
                        error_code = val
                        break
                self._record_error(source_id, source_name, error_code)
                article['_error_code'] = error_code

            exc_desc = str(exc) or type(exc).__name__
            self.logger.warning(
                f"⚠️  [{source_name}] Enrichment error: {exc_desc}"
            )
            return False

    def _record_error(
        self, key: str, source_name: str, error_code: Any
    ) -> None:
        """Increment in-memory error counter for *key* (URL domain or source_id)."""
        if not key:
            return
        count = self._error_counts.get(key, 0) + 1
        self._error_counts[key] = count
        if count >= _BLOCKED_THRESHOLD:
            self.logger.warning(
                f"🚫 [{source_name}] In-memory block after "
                f"{count} HTTP {error_code} errors (key={key})"
            )
        else:
            self.logger.debug(
                f"⚠️  [{source_name}] HTTP {error_code} error #{count} (key={key})"
            )

    def _record_timeout(
        self, key: str, source_name: str
    ) -> None:
        """Track consecutive fetch timeouts per domain (in-memory, session-scoped).

        After _TIMEOUT_THRESHOLD hits the domain is promoted into _error_counts
        at the block threshold so it is skipped for the rest of this session.
        No DB entry is written — the block resets on service restart.
        """
        if not key:
            return
        count = self._timeout_counts.get(key, 0) + 1
        self._timeout_counts[key] = count
        self.logger.warning(
            f"⏱️  [{source_name}] Timeout #{count}/{_TIMEOUT_THRESHOLD} (key={key})"
        )
        if count >= _TIMEOUT_THRESHOLD:
            already_blocked = self._error_counts.get(key, 0) >= _BLOCKED_THRESHOLD
            self._error_counts[key] = _BLOCKED_THRESHOLD
            if not already_blocked:
                self.logger.warning(
                    f"🚫 [{source_name}] In-memory block after {count} consecutive "
                    f"timeouts (key={key}) — will retry after service restart"
                )
