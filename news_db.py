"""
news_db.py — Centralised async CRUD layer for predator_news.db.

All database access in the application goes through this module.
A single aiosqlite connection is kept open for the lifetime of the process;
every await goes through aiosqlite's internal work-queue (background SQLite
thread), so the asyncio event loop is never blocked.

A ``_write_lock`` (asyncio.Lock) serialises multi-statement atomic blocks —
e.g. read-then-update sequences that must not be interleaved by another
coroutine.  Single-statement DML (INSERT OR IGNORE, ON CONFLICT DO UPDATE,
simple UPDATE/DELETE) does **not** need the lock.

Usage
-----
    # Once at startup:
    db = await NewsDatabase.open("/path/to/predator_news.db")

    # Anywhere afterwards:
    db = NewsDatabase.instance()
    inserted = await db.insert_article(article_dict)

    # At shutdown:
    await db.close()
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional, TypedDict

import aiosqlite

logger = logging.getLogger(__name__)


# ── Typed shapes for stable dict contracts ────────────────────────────────────

class QueueStats(TypedDict):
    """Shape returned by fetch_queue_stats() and consumed by /api/queues."""
    enriched:          int
    enrich_pending:    int
    enrich_failed:     int
    translated:        int
    translate_skipped: int
    translate_pending: int
    pending_by_tier:   dict  # {enrich_try: count} for is_enriched=0
    refreshed_at:      int


class ArticleStats(TypedDict):
    """Shape returned by fetch_article_stats() and consumed by /api/stats."""
    total:         int
    last_24h:      int
    last_hour:     int
    total_sources: int
    timestamp:     int


class GmtUpdate(TypedDict):
    """One row for update_gmt_batch()."""
    article_id:    str
    gmt_timestamp: str


class _TranslationRequired(TypedDict):
    is_translated: int


class TranslationValues(_TranslationRequired, total=False):
    """Values accepted by save_translation().  is_translated is mandatory."""
    translated_title:       str
    translated_description: str
    translated_content:     str


class NewsDatabase:
    """Singleton async CRUD layer backed by aiosqlite."""

    _instance: Optional["NewsDatabase"] = None

    # ── Construction ──────────────────────────────────────────────────────────

    def __init__(self, db_path: str) -> None:
        self._db_path    = db_path
        self._conn:    Optional[aiosqlite.Connection] = None
        self._ro_conn: Optional[aiosqlite.Connection] = None  # read-only; never blocks writers
        # Serialises multi-statement atomic blocks so coroutines cannot interleave
        self._write_lock = asyncio.Lock()
        # Cached queue stats — refreshed by refresh_stats_cache() every N seconds
        self._cached_stats: QueueStats = {
            "enriched": 0, "enrich_pending": 0, "enrich_failed": 0,
            "translated": 0, "translate_skipped": 0, "translate_pending": 0,
            "pending_by_tier": {},
            "refreshed_at": 0,
        }

    @classmethod
    async def open(cls, db_path: str) -> "NewsDatabase":
        """Create (or return) the singleton – connect and configure the DB."""
        if cls._instance is None:
            obj = cls(db_path)
            await obj._connect()
            cls._instance = obj
        return cls._instance

    @classmethod
    def instance(cls) -> "NewsDatabase":
        """Return the already-opened singleton (raises if not yet opened)."""
        if cls._instance is None:
            raise RuntimeError("NewsDatabase.open() has not been awaited yet")
        return cls._instance

    async def _connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path, timeout=60.0)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=60000")
        # Checkpoint automatically when WAL reaches 1000 pages (~4 MB)
        await self._conn.execute("PRAGMA wal_autocheckpoint=1000")
        await self._migrate()
        await self._conn.commit()
        # Read-only connection: runs in its own aiosqlite thread — never queues
        # behind write operations. WAL mode allows concurrent readers + 1 writer.
        self._ro_conn = await aiosqlite.connect(
            f"file:{self._db_path}?mode=ro", uri=True, timeout=10.0
        )
        self._ro_conn.row_factory = aiosqlite.Row
        await self._ro_conn.execute("PRAGMA busy_timeout=5000")
        logger.info(f"✅ NewsDatabase connected: {self._db_path}")
        # Periodic WAL checkpoint task (every 5 min) to prevent WAL from growing unbounded
        import asyncio
        self._checkpoint_task: asyncio.Task = asyncio.get_event_loop().create_task(
            self._periodic_wal_checkpoint()
        )

    async def _migrate(self) -> None:
        """Apply incremental schema migrations (idempotent)."""
        # enrich_try: 0=never tried, 1=cffi tried, 2=requests tried, 3+=playwright tried
        try:
            await self._conn.execute(
                "ALTER TABLE gm_articles ADD COLUMN enrich_try INTEGER NOT NULL DEFAULT 0"
            )
            await self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_articles_enrich_try "
                "ON gm_articles(is_enriched, enrich_try)"
            )
            logger.info("✅ Migration: added enrich_try column + index")
        except Exception:
            pass  # column already exists — ignore
        # Partial covering index for translate_pending count — avoids full-table scan
        await self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stats_translate_pending
            ON gm_articles(is_enriched, detected_language)
            WHERE is_translated = 0
            """
        )
        logger.debug("✅ Migration: idx_stats_translate_pending ensured")
        # Unique index for title_hash — every article must have one (title is mandatory)
        await self._conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_title_hash
            ON gm_articles(title_hash)
            """
        )
        logger.debug("✅ Migration: idx_articles_title_hash (UNIQUE) ensured")
        # One-time fix: strip microseconds from published_at_gmt values that were
        # stored with full microsecond precision (e.g. "2026-04-11T03:41:57.002412+00:00").
        # The bug was in the fallback branches of normalize_timestamp_to_utc which called
        # datetime.now(timezone.utc).isoformat() without .replace(microsecond=0).
        cursor = await self._conn.execute(
            """
            SELECT COUNT(*) FROM gm_articles
            WHERE published_at_gmt LIKE '%.%+%' OR published_at_gmt LIKE '%.%Z'
            """
        )
        row = await cursor.fetchone()
        affected = row[0] if row else 0
        if affected > 0:
            await self._conn.execute(
                """
                UPDATE gm_articles
                SET published_at_gmt =
                    CASE
                        WHEN published_at_gmt LIKE '%.%+%' THEN
                            substr(published_at_gmt, 1, instr(published_at_gmt, '.') - 1)
                            || substr(published_at_gmt, instr(published_at_gmt, '+'))
                        WHEN published_at_gmt LIKE '%.%Z' THEN
                            substr(published_at_gmt, 1, instr(published_at_gmt, '.') - 1) || 'Z'
                        ELSE published_at_gmt
                    END
                WHERE published_at_gmt LIKE '%.%+%' OR published_at_gmt LIKE '%.%Z'
                """
            )
            logger.info(f"✅ Migration: stripped microseconds from {affected} published_at_gmt values")

    async def open_ro_conn(self) -> "aiosqlite.Connection":
        """
        Open and return a *new* read-only aiosqlite connection to the same DB.

        Each aiosqlite.Connection runs in its own background thread, so
        multiple workers that each hold a private connection can execute
        queries truly in parallel rather than serialising through _ro_conn.

        The caller is responsible for closing the connection when done
        (``await conn.close()``).
        """
        conn = await aiosqlite.connect(
            f"file:{self._db_path}?mode=ro", uri=True, timeout=10.0
        )
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA cache_size=-8192")   # 8 MB per worker conn
        return conn

    async def _periodic_wal_checkpoint(self) -> None:
        """Run PRAGMA wal_checkpoint(PASSIVE) every 5 minutes to keep WAL small."""
        import asyncio
        while True:
            await asyncio.sleep(300)
            if self._conn is None:
                break
            try:
                await self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                logger.debug("🗄️  WAL checkpoint (PASSIVE) completed")
            except Exception as exc:
                logger.warning(f"⚠️  WAL checkpoint failed: {exc}")

    async def close(self) -> None:
        if hasattr(self, '_checkpoint_task') and self._checkpoint_task:
            self._checkpoint_task.cancel()
        if self._ro_conn:
            await self._ro_conn.close()
            self._ro_conn = None
        if self._conn:
            try:
                await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                logger.debug("🗄️  WAL checkpoint (TRUNCATE) on close")
            except Exception:
                pass
            await self._conn.close()
            self._conn = None
            NewsDatabase._instance = None
            logger.info("✅ NewsDatabase connection closed")

    # ── Internal helper ───────────────────────────────────────────────────────

    @property
    def _c(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("NewsDatabase is not connected")
        return self._conn

    @property
    def _rc(self) -> aiosqlite.Connection:
        """Read-only connection — use for SELECT-only workloads to avoid blocking writes."""
        if self._ro_conn is None:
            raise RuntimeError("NewsDatabase read-only connection is not open")
        return self._ro_conn

    # ═══════════════════════════════════════════════════════════════════════════
    # SOURCES
    # ═══════════════════════════════════════════════════════════════════════════

    async def load_sources(self) -> list[dict]:
        """Return all rows from gm_sources as a list of dicts."""
        async with self._rc.execute("SELECT * FROM gm_sources") as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def load_rss_sources(self, skip_blocked: bool = True) -> list[dict]:
        """Return all RSS sources (id_source LIKE 'rss-%')."""
        if skip_blocked:
            sql = (
                "SELECT * FROM gm_sources "
                "WHERE id_source LIKE 'rss-%' "
                "  AND (fetch_blocked IS NULL OR fetch_blocked != 1)"
            )
        else:
            sql = "SELECT * FROM gm_sources WHERE id_source LIKE 'rss-%'"
        async with self._rc.execute(sql) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def insert_source_if_new(self, source: dict) -> bool:
        """
        INSERT OR IGNORE a source.  Returns True if a new row was created.
        Single-statement – no lock needed.
        """
        cols = ("id_source", "name", "description", "url",
                "category", "language", "country")
        vals = tuple(source.get(c, "") or "" for c in cols)
        is_proxy = int(source.get("is_proxy_aggregator", 0) or 0)
        cur = await self._c.execute(
            "INSERT OR IGNORE INTO gm_sources "
            "(id_source, name, description, url, category, language, country, is_proxy_aggregator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            vals + (is_proxy,),
        )
        await self._c.commit()
        return cur.rowcount > 0

    async def update_source_timezone(self, source_id: str, timezone: str) -> None:
        """Update the detected timezone for a source."""
        await self._c.execute(
            "UPDATE gm_sources SET timezone=? WHERE id_source=?",
            (timezone, source_id),
        )
        await self._c.commit()

    async def update_source_timezone_and_enable(
        self, source_id: str, timezone: str
    ) -> None:
        """Set timezone and flip use_timezone=1 in a single commit."""
        await self._c.execute(
            "UPDATE gm_sources SET timezone=?, use_timezone=1 WHERE id_source=?",
            (timezone, source_id),
        )
        await self._c.commit()

    async def get_source_block_status(self, source_id: str) -> tuple[int, int]:
        """Return (fetch_blocked, blocked_count) or (0, 0) if not found."""
        async with self._rc.execute(
            "SELECT fetch_blocked, blocked_count FROM gm_sources WHERE id_source=?",
            (source_id,),
        ) as cur:
            row = await cur.fetchone()
        return (row[0] or 0, row[1] or 0) if row else (0, 0)

    async def increment_source_blocked_count(
        self,
        source_id: str,
        source_name: str = "",
        error_code: Any = 403,
    ) -> None:
        """
        Increment blocked_count; auto-set fetch_blocked=1 when count reaches 3.
        Uses _write_lock so the SELECT → UPDATE is atomic.
        """
        async with self._write_lock:
            async with self._c.execute(
                "SELECT blocked_count, fetch_blocked FROM gm_sources WHERE id_source=?",
                (source_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return
            current_count, currently_blocked = row[0] or 0, row[1] or 0
            new_count    = current_count + 1
            should_block = 1 if new_count >= 3 else 0
            await self._c.execute(
                "UPDATE gm_sources SET blocked_count=?, fetch_blocked=? WHERE id_source=?",
                (new_count, should_block, source_id),
            )
            await self._c.commit()

        if should_block == 1 and currently_blocked == 0:
            logger.warning(
                f"🚫 [{source_name}] Blocklisted after {new_count} "
                f"HTTP {error_code} errors — future fetches skipped"
            )
        else:
            logger.debug(f"⚠️  [{source_name}] HTTP {error_code} error #{new_count}")

    async def get_blocked_sources_for_probe(self) -> list[dict]:
        """Return blocked sources with a sample article URL, lowest blocked_count first."""
        async with self._rc.execute(
            """
            SELECT s.id_source, s.name, s.blocked_count,
                   a.url AS sample_url
            FROM gm_sources s
            JOIN gm_articles a ON a.id_article = (
                SELECT MAX(id_article)
                FROM gm_articles
                WHERE id_source = s.id_source
                  AND url IS NOT NULL AND url != ''
            )
            WHERE s.fetch_blocked = 1
            ORDER BY s.blocked_count ASC, s.name
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def unblock_source(self, source_id: str) -> int:
        """
        Reset fetch_blocked=0 / blocked_count=0 and re-queue all non-enriched
        articles for the source.  Returns the number of articles re-queued.
        Atomic: both UPDATEs are committed together under _write_lock.
        """
        async with self._write_lock:
            await self._c.execute(
                "UPDATE gm_sources SET fetch_blocked=0, blocked_count=0 WHERE id_source=?",
                (source_id,),
            )
            cur = await self._c.execute(
                "UPDATE gm_articles SET is_enriched=0 WHERE id_source=? AND is_enriched != 1",
                (source_id,),
            )
            await self._c.commit()
            return cur.rowcount

    # ═══════════════════════════════════════════════════════════════════════════
    # ARTICLES
    # ═══════════════════════════════════════════════════════════════════════════

    async def insert_article(self, article: dict) -> bool:
        """
        INSERT OR IGNORE article into gm_articles.
        Returns True if a new row was created, False if it already existed.
        """
        cols         = list(article.keys())
        placeholders = ", ".join("?" * len(cols))
        col_list     = ", ".join(cols)
        cur = await self._c.execute(
            f"INSERT OR IGNORE INTO gm_articles ({col_list}) VALUES ({placeholders})",
            tuple(article[c] for c in cols),
        )
        await self._c.commit()
        return cur.rowcount > 0

    async def insert_articles_batch(self, articles: list[dict]) -> int:
        """
        INSERT OR IGNORE a list of articles in a single transaction.
        Returns the number of rows actually inserted (duplicates are silently ignored).
        Much faster than calling insert_article() per row — one fsync instead of N.
        """
        if not articles:
            return 0
        cols         = list(articles[0].keys())
        placeholders = ", ".join("?" * len(cols))
        col_list     = ", ".join(cols)
        sql          = f"INSERT OR IGNORE INTO gm_articles ({col_list}) VALUES ({placeholders})"
        inserted     = 0
        # No _write_lock needed: INSERT OR IGNORE is atomic per statement;
        # the consumer is already serial and SQLite WAL handles concurrent readers.
        for article in articles:
            cur = await self._c.execute(sql, tuple(article[c] for c in cols))
            inserted += cur.rowcount
        await self._c.commit()
        return inserted

    async def find_by_title_hash(self, title_hash: str) -> Optional[dict]:
        """
        Return the first enriched article with the same title_hash (cross-feed
        content reuse), or None.
        """
        async with self._rc.execute(
            """
            SELECT author, description, content, urlToImage
            FROM gm_articles
            WHERE title_hash = ?
              AND is_enriched = 1
              AND content IS NOT NULL AND content != ''
            LIMIT 1
            """,
            (title_hash,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def find_by_title_hash_bulk(
        self,
        hashes: list[str],
        conn: Optional["aiosqlite.Connection"] = None,
    ) -> dict[str, dict]:
        """
        Kept for backwards compatibility.  New code should use
        ``find_existing_title_hashes`` which is faster (covering-index only).
        """
        existing = await self.find_existing_title_hashes(hashes, conn=conn)
        return {h: {} for h in existing}

    async def find_existing_title_hashes(
        self,
        hashes: list[str],
        conn: Optional["aiosqlite.Connection"] = None,
    ) -> set[str]:
        """
        Return the subset of *hashes* that already exist in gm_articles.

        Uses ``idx_articles_title_hash`` as a **covering index** — SQLite
        resolves the query entirely from the index pages without reading any
        table rows.  This is O(log N) per hash and involves no data I/O.

        Pass ``conn`` to use a dedicated per-worker read connection (each
        aiosqlite.Connection has its own background thread, so N workers with
        N private connections run their queries in parallel).
        """
        if not hashes:
            return set()
        placeholders = ", ".join("?" * len(hashes))
        c = conn if conn is not None else self._rc
        existing: set[str] = set()
        async with c.execute(
            f"SELECT title_hash FROM gm_articles WHERE title_hash IN ({placeholders})",
            hashes,
        ) as cur:
            async for row in cur:
                existing.add(row[0])
        return existing

    async def fetch_pending_enrichment(self, limit: int, enrich_try: int = 0) -> list[dict]:
        """
        Return up to *limit* articles pending enrichment for the given tier,
        newest-first.  enrich_try selects the pipeline tier:
          0 = never tried (cffi tier)
          1 = cffi failed (requests tier)
          2 = requests failed (playwright tier)
        """
        async with self._rc.execute(
            """
            SELECT a.id_article, a.id_source, a.url, a.author,
                   a.description, a.content, a.urlToImage,
                   a.enrich_try,
                   s.name AS source_name
            FROM gm_articles a
            LEFT JOIN gm_sources s ON s.id_source = a.id_source
            WHERE a.is_enriched = 0
              AND a.enrich_try = ?
              AND a.enrich_try <= 2
              AND a.url IS NOT NULL AND a.url != ''
              AND (s.fetch_blocked IS NULL OR s.fetch_blocked != 1)
            ORDER BY a.published_at_gmt DESC
            LIMIT ?
            """,
            (enrich_try, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def mark_enrich_attempt_failed(self, article_id: str, current_try: int) -> None:
        """
        Record that the current enrichment tier failed for *article_id*.
        Increments enrich_try so the article advances to the next tier.
        If current_try >= 2 (playwright failed) marks is_enriched=-1 (give up).
        """
        if current_try >= 2:
            await self._c.execute(
                "UPDATE gm_articles SET is_enriched = -1 WHERE id_article = ?",
                (article_id,),
            )
        else:
            await self._c.execute(
                "UPDATE gm_articles SET enrich_try = enrich_try + 1 WHERE id_article = ?",
                (article_id,),
            )
        await self._c.commit()

    async def save_enriched_article(
        self,
        article_id: str,
        *,
        author:       Optional[str],
        description:  Optional[str],
        content:      Optional[str],
        url_to_image: Optional[str],
        is_enriched:  int,
        commit:       bool = True,
    ) -> None:
        """
        Persist enrichment results atomically.
        When is_enriched=1 the article is also reset to is_translated=0 so the
        translation pipeline picks it up on its next cycle.

        Set commit=False to batch multiple writes and call self._c.commit()
        manually afterwards — reduces fsync overhead under high write load.
        """
        await self._c.execute(
            """
            UPDATE gm_articles
            SET author      = COALESCE(?, author),
                description = COALESCE(?, description),
                content     = ?,
                is_enriched = ?,
                urlToImage  = COALESCE(?, urlToImage),
                is_translated = CASE WHEN ? = 1 AND is_translated != 1 THEN 0 ELSE is_translated END
            WHERE id_article = ?
            """,
            (author, description, content, is_enriched,
             url_to_image, is_enriched, article_id),
        )
        if commit:
            await self._c.commit()

    async def save_enrichment_failure(
        self, article_id: str, has_content: bool
    ) -> None:
        """
        Mark an article whose enrichment attempt failed.
        has_content=True  → is_enriched=1  (article already had data)
        has_content=False → is_enriched=-1 (nothing useful; skip translation)
        """
        val = 1 if has_content else -1
        await self._c.execute(
            "UPDATE gm_articles SET is_enriched=? WHERE id_article=?",
            (val, article_id),
        )
        await self._c.commit()

    async def bulk_close_blocked_source_articles(self) -> None:
        """
        For all pending articles whose source is blocked:
          - promote to is_enriched=1 if the article already has content/description
          - otherwise mark is_enriched=-1 to skip enrichment
        Prevents the backfill producer from wasting concurrency slots on dead sources.
        """
        await self._c.execute(
            """
            UPDATE gm_articles
            SET is_enriched = CASE
                WHEN (description IS NOT NULL AND description != '')
                  OR (content     IS NOT NULL AND content     != '') THEN 1
                ELSE -1
            END
            WHERE is_enriched = 0
              AND id_source IN (SELECT id_source FROM gm_sources WHERE fetch_blocked = 1)
            """
        )
        await self._c.commit()

    async def bulk_give_up_exhausted_articles(self) -> int:
        """
        Mark is_enriched=-1 for articles stuck with enrich_try > 2 and is_enriched=0.
        These can never be picked up by any backfill tier (fetch_pending_enrichment
        filters enrich_try <= 2), so they would otherwise be counted in enrich_pending
        forever without appearing in any tier.
        """
        cur = await self._c.execute(
            "UPDATE gm_articles SET is_enriched = -1 "
            "WHERE is_enriched = 0 AND enrich_try > 2"
        )
        await self._c.commit()
        return cur.rowcount

    async def fetch_pending_translation(self, batch_size: int) -> list[dict]:
        """
        Return up to *batch_size* articles pending translation using the
        optimised view v_articles_pending_translation.

        Articles are interleaved by backend so that Google and NLLB workers
        both receive work concurrently.  Each backend contributes at most
        half the batch; remaining slots go to whichever backend has more.
        """
        half = batch_size // 2
        # Fetch up to half from each backend ordered by recency
        async with self._rc.execute(
            """
            SELECT id_article, detected_language, title, description, content
            FROM v_articles_pending_translation
            WHERE translate_backend = 'google'
            ORDER BY translate_without_enrichment DESC, inserted_at_ms DESC
            LIMIT ?
            """,
            (half,),
        ) as cur:
            google_rows = [dict(r) for r in await cur.fetchall()]

        async with self._rc.execute(
            """
            SELECT id_article, detected_language, title, description, content
            FROM v_articles_pending_translation
            WHERE translate_backend = 'nllb'
               OR translate_backend IS NULL
            ORDER BY translate_without_enrichment DESC, inserted_at_ms DESC
            LIMIT ?
            """,
            (half,),
        ) as cur:
            nllb_rows = [dict(r) for r in await cur.fetchall()]

        # If one backend is short, fill from the other up to batch_size
        shortage = batch_size - len(google_rows) - len(nllb_rows)
        if shortage > 0 and len(google_rows) < half:
            nllb_rows = nllb_rows[:half + shortage]
        elif shortage > 0 and len(nllb_rows) < half:
            google_rows = google_rows[:half + shortage]

        # Interleave so workers for both backends get fed right away
        result: list[dict] = []
        for g, n in zip(google_rows, nllb_rows):
            result.append(g)
            result.append(n)
        result.extend(google_rows[len(nllb_rows):])
        result.extend(nllb_rows[len(google_rows):])
        return result

    async def bulk_skip_non_translatable(self) -> int:
        """
        Mark is_translated=-1 for articles whose detected_language doesn't
        require translation: NULL language, translate=0, or language not in
        the languages table.

        Also resets is_translated=-1 back to 0 for articles whose language
        was later enabled for translation (translate changed from 0 to 1),
        so they get picked up on the next cycle.

        Returns the number of rows updated (skip + restore combined).
        """
        # Skip non-translatable
        cur_skip = await self._c.execute(
            """
            UPDATE gm_articles
            SET is_translated = -1
            WHERE is_translated = 0
              AND (
                  detected_language IS NULL
                  OR detected_language NOT IN (
                      SELECT language_code FROM languages WHERE translate = 1
                  )
              )
            """
        )
        # Restore articles incorrectly skipped when language was later enabled
        cur_restore = await self._c.execute(
            """
            UPDATE gm_articles
            SET is_translated = 0
            WHERE is_translated = -1
              AND detected_language IN (
                  SELECT language_code FROM languages WHERE translate = 1
              )
            """
        )
        await self._c.commit()
        return cur_skip.rowcount + cur_restore.rowcount

    async def get_proxy_articles_pending_resolution(self, limit: int = 30) -> list[dict]:
        """Return articles with is_enriched=-2 (proxy URL not yet resolved)."""
        async with self._rc.execute(
            "SELECT id_article, url FROM gm_articles "
            "WHERE is_enriched = -2 "
            "ORDER BY inserted_at_ms DESC "
            "LIMIT ?",
            (limit,),
        ) as cur:
            return [{"id_article": r[0], "url": r[1]} for r in await cur.fetchall()]

    async def resolve_proxy_article_url(self, id_article: bytes, real_url: str) -> None:
        """Update the article URL to the real (resolved) URL and queue for enrichment."""
        await self._c.execute(
            "UPDATE gm_articles SET url = ?, is_enriched = 0 "
            "WHERE id_article = ? AND is_enriched = -2",
            (real_url, id_article),
        )
        await self._c.commit()

    async def save_translation(self, article_id: str, values: TranslationValues) -> None:
        """
        Persist translation results atomically.
        *values* must include 'is_translated' and may include
        translated_title, translated_description, translated_content.
        """
        import time as _time
        _ALLOWED = frozenset({
            "is_translated", "translated_title",
            "translated_description", "translated_content",
        })
        params = {k: v for k, v in values.items() if k in _ALLOWED}
        if "is_translated" not in params:
            raise ValueError("save_translation requires 'is_translated'")
        # Record timestamp only for successfully translated articles
        if params.get("is_translated") == 1:
            params["translated_at_ms"] = int(_time.time() * 1000)
        params["_id"] = article_id
        set_clause = ", ".join(f"{k}=:{k}" for k in params if k != "_id")
        await self._c.execute(
            f"UPDATE gm_articles SET {set_clause} WHERE id_article=:_id",
            params,
        )
        await self._c.commit()

    async def update_translate_backend(self, language_code: str, backend: str) -> None:
        """Update translate_backend for a language after permanent failure auto-discovery."""
        await self._c.execute(
            "UPDATE languages SET translate_backend=? WHERE language_code=?",
            (backend, language_code),
        )
        await self._c.commit()

    async def fetch_articles_missing_gmt(
        self, source_id: str
    ) -> list[tuple[str, str]]:
        """
        Return (id_article, publishedAt) for articles of *source_id* that
        have no published_at_gmt yet.
        """
        async with self._rc.execute(
            """
            SELECT id_article, publishedAt
            FROM gm_articles
            WHERE id_source = ?
              AND published_at_gmt IS NULL
              AND publishedAt IS NOT NULL
            """,
            (source_id,),
        ) as cur:
            return await cur.fetchall()

    async def update_gmt_batch(self, updates: list[GmtUpdate]) -> None:
        """
        Bulk-update published_at_gmt.
        Each element: {"article_id": str, "gmt_timestamp": str}
        """
        if not updates:
            return
        await self._c.executemany(
            "UPDATE gm_articles SET published_at_gmt=:gmt_timestamp WHERE id_article=:article_id",
            updates,
        )
        await self._c.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # BLOCKED DOMAINS
    # ═══════════════════════════════════════════════════════════════════════════

    async def load_blocked_domains(self) -> list[tuple[str, int]]:
        """Return [(domain, blocked_count)] for all is_blocked=1 entries."""
        async with self._rc.execute(
            "SELECT domain, blocked_count FROM gm_blocked_domains WHERE is_blocked=1"
        ) as cur:
            return await cur.fetchall()

    async def increment_blocked_domain(
        self, domain: str, error_code: Any = 403
    ) -> tuple[int, bool]:
        """
        Upsert blocked-domain counter.
        Returns (new_count, newly_became_blocked).
        Caller should call bulk_remove_pending_for_domain() when newly_became_blocked=True.
        Uses _write_lock so UPSERT + SELECT are not interleaved.
        """
        async with self._write_lock:
            await self._c.execute(
                """
                INSERT INTO gm_blocked_domains
                    (domain, blocked_count, is_blocked, last_error, updated_at)
                VALUES (?, 1, 0, ?, datetime('now'))
                ON CONFLICT(domain) DO UPDATE SET
                    blocked_count = blocked_count + 1,
                    last_error    = excluded.last_error,
                    updated_at    = datetime('now'),
                    is_blocked    = CASE
                        WHEN blocked_count + 1 >= 3 THEN 1
                        ELSE is_blocked
                    END
                """,
                (domain, str(error_code)),
            )
            await self._c.commit()
            async with self._c.execute(
                "SELECT blocked_count, is_blocked FROM gm_blocked_domains WHERE domain=?",
                (domain,),
            ) as cur:
                row = await cur.fetchone()
        count      = row[0] if row else 1
        is_blocked = bool(row[1]) if row else False
        return count, is_blocked

    async def bulk_remove_pending_for_domain(self, domain: str) -> int:
        """
        Set is_enriched=-1 for pending articles whose URL contains *domain*.
        Returns the number of articles removed from the enrichment queue.
        """
        cur = await self._c.execute(
            """
            UPDATE gm_articles SET is_enriched = -1
            WHERE is_enriched = 0
              AND (content IS NULL OR content = '')
              AND url LIKE ?
            """,
            (f"%{domain}%",),
        )
        await self._c.commit()
        return cur.rowcount

    # ═══════════════════════════════════════════════════════════════════════════
    # QUEUE STATS  (used by GET /api/queues)
    # ═══════════════════════════════════════════════════════════════════════════

    async def fetch_queue_stats(self) -> QueueStats:
        """
        Return aggregate counts for the /api/queues response.

        Uses the read-only connection (_rc) so queries never queue behind write
        operations. Two queries instead of four:
          1. One combined GROUP BY scan over idx_articles_enriched_translated
             replaces the former two separate GROUP BY queries.
          2. Partial-index lookup for translate_pending via idx_stats_translate_pending.
        """
        rc = self._rc

        # Single index scan replaces two separate GROUP BY queries.
        # idx_articles_enriched_translated covers (is_enriched, is_translated).
        async with rc.execute(
            "SELECT is_enriched, is_translated, COUNT(*) "
            "FROM gm_articles GROUP BY is_enriched, is_translated"
        ) as cur:
            enrich_map: dict[int, int] = {}
            trans_map:  dict[int, int] = {}
            for row in await cur.fetchall():
                ie, it, cnt = row[0], row[1], row[2]
                enrich_map[ie] = enrich_map.get(ie, 0) + cnt
                trans_map[it]  = trans_map.get(it,  0) + cnt

        # Fast via idx_articles_enrich_try (is_enriched, enrich_try)
        async with rc.execute(
            "SELECT enrich_try, COUNT(*) FROM gm_articles "
            "WHERE is_enriched = 0 GROUP BY enrich_try"
        ) as cur:
            tier_map = {r[0]: r[1] for r in await cur.fetchall()}

        # Translate pending — uses partial index idx_stats_translate_pending
        async with rc.execute(
            """
            SELECT COUNT(*) FROM gm_articles
            WHERE is_translated = 0
              AND is_enriched IN (1, -1)
              AND detected_language IN (
                  SELECT language_code FROM languages WHERE translate = 1
              )
            """
        ) as cur:
            tp_row = await cur.fetchone()

        return {
            "enriched":          enrich_map.get(1,  0),
            "enrich_pending":    enrich_map.get(0,  0),
            "enrich_failed":     enrich_map.get(-1, 0),
            "translated":        trans_map.get(1,   0),
            "translate_skipped": trans_map.get(-1, 0) + trans_map.get(-2, 0),
            "translate_pending": tp_row[0] if tp_row else 0,
            "pending_by_tier":   tier_map,
            "refreshed_at":      int(time.time() * 1000),
        }

    @property
    def cached_stats(self) -> QueueStats:
        """Return the last cached queue statistics (updated by refresh_stats_cache)."""
        return self._cached_stats

    async def refresh_stats_cache(self) -> QueueStats:
        """Fetch fresh stats, store them in the cache, and return them."""
        stats = await self.fetch_queue_stats()
        self._cached_stats = stats
        return stats

    async def fetch_article_stats(self) -> ArticleStats:
        """Return article/source counts for the /api/stats endpoint."""
        now_ms = int(time.time() * 1000)
        async with self._rc.execute("SELECT COUNT(*) FROM gm_articles") as cur:
            total = (await cur.fetchone())[0]
        async with self._rc.execute(
            "SELECT COUNT(*) FROM gm_articles WHERE inserted_at_ms > ?",
            (now_ms - 86_400_000,),
        ) as cur:
            last_24h = (await cur.fetchone())[0]
        async with self._rc.execute(
            "SELECT COUNT(*) FROM gm_articles WHERE inserted_at_ms > ?",
            (now_ms - 3_600_000,),
        ) as cur:
            last_hour = (await cur.fetchone())[0]
        async with self._rc.execute("SELECT COUNT(*) FROM gm_sources") as cur:
            total_sources = (await cur.fetchone())[0]
        return {
            "total":         total,
            "last_24h":      last_24h,
            "last_hour":     last_hour,
            "total_sources": total_sources,
            "timestamp":     now_ms,
        }

    async def fetch_pending_by_language(self, limit: int = 10) -> list[dict]:
        """Return pending-translation counts grouped by detected language, descending."""
        async with self._rc.execute(
            """
            SELECT detected_language, language_name, target_language, COUNT(*) AS n
            FROM v_articles_pending_translation
            GROUP BY detected_language
            ORDER BY n DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
