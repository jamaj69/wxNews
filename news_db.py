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

    async def close(self) -> None:
        if self._ro_conn:
            await self._ro_conn.close()
            self._ro_conn = None
        if self._conn:
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
        cur = await self._c.execute(
            "INSERT OR IGNORE INTO gm_sources "
            "(id_source, name, description, url, category, language, country) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            vals,
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
    ) -> None:
        """
        Persist enrichment results atomically.
        When is_enriched=1 the article is also reset to is_translated=0 so the
        translation pipeline picks it up on its next cycle.
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

    async def fetch_pending_translation(self, batch_size: int) -> list[dict]:
        """
        Return up to *batch_size* articles pending translation using the
        optimised view v_articles_pending_translation.
        """
        async with self._rc.execute(
            """
            SELECT id_article, detected_language, title, description, content
            FROM v_articles_pending_translation
            ORDER BY translate_without_enrichment DESC, inserted_at_ms DESC
            LIMIT ?
            """,
            (batch_size,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def bulk_skip_non_translatable(self) -> int:
        """
        Mark is_translated=-1 for articles whose detected_language doesn't
        require translation (translate=0 or language not in the languages table).
        Returns the number of rows updated.
        """
        cur = await self._c.execute(
            """
            UPDATE gm_articles
            SET is_translated = -1
            WHERE is_translated = 0
              AND detected_language IS NOT NULL
              AND detected_language NOT IN (
                  SELECT language_code FROM languages WHERE translate = 1
              )
            """
        )
        await self._c.commit()
        return cur.rowcount

    async def save_translation(self, article_id: str, values: TranslationValues) -> None:
        """
        Persist translation results atomically.
        *values* must include 'is_translated' and may include
        translated_title, translated_description, translated_content.
        """
        _ALLOWED = frozenset({
            "is_translated", "translated_title",
            "translated_description", "translated_content",
        })
        params = {k: v for k, v in values.items() if k in _ALLOWED}
        if "is_translated" not in params:
            raise ValueError("save_translation requires 'is_translated'")
        params["_id"] = article_id
        set_clause = ", ".join(f"{k}=:{k}" for k in params if k != "_id")
        await self._c.execute(
            f"UPDATE gm_articles SET {set_clause} WHERE id_article=:_id",
            params,
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
            "translate_skipped": trans_map.get(-1,  0),
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
