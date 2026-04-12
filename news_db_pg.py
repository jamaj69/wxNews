"""
news_db_pg.py — Async CRUD layer backed by PostgreSQL (asyncpg).

Drop-in replacement for news_db.py.  The public API is identical; only the
internal DB wiring changes:

  aiosqlite  →  asyncpg connection pool
  ?          →  $1, $2, $3 positional placeholders
  INSERT OR IGNORE  →  INSERT … ON CONFLICT DO NOTHING
  _write_lock (asyncio.Lock)  →  removed (PostgreSQL MVCC handles concurrency)
  _ro_conn / open_ro_conn()   →  removed (pool connections are all concurrent)
  PRAGMAs     →  removed

Connection string is read from the ``DATABASE_URL`` environment variable
(standard SQLAlchemy / asyncpg format):

    postgresql://user:password@host:5432/dbname

Usage
-----
    # Once at startup:
    db = await NewsDatabase.open("postgresql://user:pass@localhost/predator")

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

import asyncpg

logger = logging.getLogger(__name__)


# ── Typed shapes (identical to news_db.py) ────────────────────────────────────

class QueueStats(TypedDict):
    enriched:          int
    enrich_pending:    int
    enrich_failed:     int
    translated:        int
    translate_skipped: int
    translate_pending: int
    pending_by_tier:   dict
    refreshed_at:      int


class ArticleStats(TypedDict):
    total:         int
    last_24h:      int
    last_hour:     int
    total_sources: int
    timestamp:     int


class GmtUpdate(TypedDict):
    article_id:    str
    gmt_timestamp: str


class _TranslationRequired(TypedDict):
    is_translated: int


class TranslationValues(_TranslationRequired, total=False):
    translated_title:       str
    translated_description: str
    translated_content:     str


def _row_to_dict(record: asyncpg.Record) -> dict:
    """Convert an asyncpg.Record to a plain dict."""
    return dict(record)


class NewsDatabase:
    """Singleton async CRUD layer backed by asyncpg (PostgreSQL)."""

    _instance: Optional["NewsDatabase"] = None

    # ── Construction ──────────────────────────────────────────────────────────

    def __init__(self, dsn: str) -> None:
        self._dsn  = dsn
        self._pool: Optional[asyncpg.Pool] = None
        self._cached_stats: QueueStats = {
            "enriched": 0, "enrich_pending": 0, "enrich_failed": 0,
            "translated": 0, "translate_skipped": 0, "translate_pending": 0,
            "pending_by_tier": {},
            "refreshed_at": 0,
        }

    @classmethod
    async def open(cls, dsn: str) -> "NewsDatabase":
        if cls._instance is None:
            obj = cls(dsn)
            await obj._connect()
            cls._instance = obj
        return cls._instance

    @classmethod
    def instance(cls) -> "NewsDatabase":
        if cls._instance is None:
            raise RuntimeError("NewsDatabase.open() has not been awaited yet")
        return cls._instance

    async def _connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=2,
            max_size=20,
            command_timeout=60,
            statement_cache_size=100,
        )
        async with self._pool.acquire() as conn:
            await self._migrate(conn)
        logger.info(f"✅ NewsDatabase (pg) connected: {self._dsn.split('@')[-1]}")

    async def _migrate(self, conn: asyncpg.Connection) -> None:
        """Apply incremental schema migrations (idempotent)."""

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS gm_sources (
                id_source       TEXT PRIMARY KEY,
                name            TEXT NOT NULL DEFAULT '',
                description     TEXT NOT NULL DEFAULT '',
                url             TEXT NOT NULL DEFAULT '',
                category        TEXT NOT NULL DEFAULT '',
                language        TEXT NOT NULL DEFAULT '',
                country         TEXT NOT NULL DEFAULT '',
                timezone        TEXT,
                use_timezone    INTEGER NOT NULL DEFAULT 0,
                fetch_blocked   INTEGER,
                blocked_count   INTEGER NOT NULL DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS gm_articles (
                id_article          TEXT PRIMARY KEY,
                id_source           TEXT,
                author              TEXT,
                title               TEXT,
                description         TEXT,
                url                 TEXT,
                urlToImage          TEXT,
                publishedAt         TEXT,
                published_at_gmt    TEXT,
                content             TEXT,
                inserted_at_ms      BIGINT,
                detected_language   TEXT,
                language_confidence REAL,
                is_enriched         INTEGER NOT NULL DEFAULT 0,
                enrich_try          INTEGER NOT NULL DEFAULT 0,
                is_translated       INTEGER NOT NULL DEFAULT 0,
                translated_title        TEXT,
                translated_description  TEXT,
                translated_content      TEXT,
                title_hash          TEXT
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS gm_blocked_domains (
                domain        TEXT PRIMARY KEY,
                blocked_count INTEGER NOT NULL DEFAULT 0,
                is_blocked    INTEGER NOT NULL DEFAULT 0,
                last_error    TEXT,
                updated_at    TEXT
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS languages (
                language_code              TEXT PRIMARY KEY,
                language_name              TEXT,
                translate                  INTEGER NOT NULL DEFAULT 0,
                translate_to               TEXT,
                translator_code            TEXT,
                translate_backend          TEXT,
                translate_without_enrichment INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Indexes (idempotent)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_articles_enrich_try
            ON gm_articles(is_enriched, enrich_try)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_articles_title_hash
            ON gm_articles(title_hash)
            WHERE title_hash IS NOT NULL
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_stats_translate_pending
            ON gm_articles(is_enriched, detected_language)
            WHERE is_translated = 0
        """)

        # View for pending translation
        await conn.execute("""
            CREATE OR REPLACE VIEW v_articles_pending_translation AS
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
              AND (
                  a.is_enriched IN (1, -1)
                  OR (l.translate_without_enrichment = 1 AND a.enrich_try >= 3)
              )
        """)

        logger.info("✅ Migration: schema ensured")

    async def open_ro_conn(self) -> asyncpg.Connection:
        """
        Acquire a connection from the pool for a worker.
        Caller is responsible for releasing it (``await conn.close()`` or
        prefer using ``async with self._pool.acquire() as conn``).

        Unlike aiosqlite, all asyncpg connections are full-featured and
        concurrent — no separate read-only connection needed.
        """
        return await self._pool.acquire()

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
            NewsDatabase._instance = None
            logger.info("✅ NewsDatabase (pg) connection pool closed")

    # ── Internal context manager helper ──────────────────────────────────────

    def _acquire(self):
        """``async with self._acquire() as conn`` — shorthand for pool.acquire()."""
        return self._pool.acquire()

    # ═══════════════════════════════════════════════════════════════════════════
    # SOURCES
    # ═══════════════════════════════════════════════════════════════════════════

    async def load_sources(self) -> list[dict]:
        async with self._acquire() as conn:
            rows = await conn.fetch("SELECT * FROM gm_sources")
        return [_row_to_dict(r) for r in rows]

    async def load_rss_sources(self, skip_blocked: bool = True) -> list[dict]:
        if skip_blocked:
            sql = (
                "SELECT * FROM gm_sources "
                "WHERE id_source LIKE 'rss-%' "
                "  AND (fetch_blocked IS NULL OR fetch_blocked != 1)"
            )
        else:
            sql = "SELECT * FROM gm_sources WHERE id_source LIKE 'rss-%'"
        async with self._acquire() as conn:
            rows = await conn.fetch(sql)
        return [_row_to_dict(r) for r in rows]

    async def insert_source_if_new(self, source: dict) -> bool:
        cols = ("id_source", "name", "description", "url",
                "category", "language", "country")
        vals = tuple(source.get(c, "") or "" for c in cols)
        col_list = ", ".join(cols)
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        async with self._acquire() as conn:
            result = await conn.execute(
                f"INSERT INTO gm_sources ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT(id_source) DO NOTHING",
                *vals,
            )
        return result == "INSERT 0 1"

    async def update_source_timezone(self, source_id: str, timezone: str) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE gm_sources SET timezone=$1 WHERE id_source=$2",
                timezone, source_id,
            )

    async def update_source_timezone_and_enable(
        self, source_id: str, timezone: str
    ) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE gm_sources SET timezone=$1, use_timezone=1 WHERE id_source=$2",
                timezone, source_id,
            )

    async def get_source_block_status(self, source_id: str) -> tuple[int, int]:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT fetch_blocked, blocked_count FROM gm_sources WHERE id_source=$1",
                source_id,
            )
        return (row["fetch_blocked"] or 0, row["blocked_count"] or 0) if row else (0, 0)

    async def increment_source_blocked_count(
        self,
        source_id: str,
        source_name: str = "",
        error_code: Any = 403,
    ) -> None:
        """
        Increment blocked_count; auto-set fetch_blocked=1 when count reaches 3.
        Uses a single atomic UPDATE … RETURNING to avoid a read-then-write race.
        """
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE gm_sources
                SET blocked_count = blocked_count + 1,
                    fetch_blocked = CASE WHEN blocked_count + 1 >= 3 THEN 1 ELSE fetch_blocked END
                WHERE id_source = $1
                RETURNING blocked_count, fetch_blocked
                """,
                source_id,
            )
        if row is None:
            return
        new_count  = row["blocked_count"]
        is_blocked = row["fetch_blocked"]
        if is_blocked == 1 and new_count == 3:
            logger.warning(
                f"🚫 [{source_name}] Blocklisted after {new_count} "
                f"HTTP {error_code} errors — future fetches skipped"
            )
        else:
            logger.debug(f"⚠️  [{source_name}] HTTP {error_code} error #{new_count}")

    async def get_blocked_sources_for_probe(self) -> list[dict]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
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
            )
        return [_row_to_dict(r) for r in rows]

    async def unblock_source(self, source_id: str) -> int:
        async with self._acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE gm_sources SET fetch_blocked=0, blocked_count=0 "
                    "WHERE id_source=$1",
                    source_id,
                )
                result = await conn.execute(
                    "UPDATE gm_articles SET is_enriched=0 "
                    "WHERE id_source=$1 AND is_enriched != 1",
                    source_id,
                )
        return int(result.split()[-1])

    # ═══════════════════════════════════════════════════════════════════════════
    # ARTICLES
    # ═══════════════════════════════════════════════════════════════════════════

    async def insert_article(self, article: dict) -> bool:
        cols         = list(article.keys())
        col_list     = ", ".join(cols)
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        async with self._acquire() as conn:
            result = await conn.execute(
                f"INSERT INTO gm_articles ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT(id_article) DO NOTHING",
                *[article[c] for c in cols],
            )
        return result == "INSERT 0 1"

    async def insert_articles_batch(self, articles: list[dict]) -> int:
        """
        INSERT … ON CONFLICT DO NOTHING for a list of articles.
        Uses a single COPY-style executemany for efficiency.
        Returns the number of rows actually inserted.
        """
        if not articles:
            return 0
        cols         = list(articles[0].keys())
        col_list     = ", ".join(cols)
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        sql          = (
            f"INSERT INTO gm_articles ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(id_article) DO NOTHING"
        )
        inserted = 0
        async with self._acquire() as conn:
            async with conn.transaction():
                for article in articles:
                    result = await conn.execute(sql, *[article[c] for c in cols])
                    if result == "INSERT 0 1":
                        inserted += 1
        return inserted

    async def find_by_title_hash(self, title_hash: str) -> Optional[dict]:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT author, description, content, "urlToImage"
                FROM gm_articles
                WHERE title_hash = $1
                  AND is_enriched = 1
                  AND content IS NOT NULL AND content != ''
                LIMIT 1
                """,
                title_hash,
            )
        return _row_to_dict(row) if row else None

    async def find_by_title_hash_bulk(
        self,
        hashes: list[str],
        conn: Optional[asyncpg.Connection] = None,
    ) -> dict[str, dict]:
        """Backwards compatibility shim — delegates to find_existing_title_hashes."""
        existing = await self.find_existing_title_hashes(hashes, conn=conn)
        return {h: {} for h in existing}

    async def find_existing_title_hashes(
        self,
        hashes: list[str],
        conn: Optional[asyncpg.Connection] = None,
    ) -> set[str]:
        """
        Return the subset of *hashes* already in gm_articles.
        Uses the covering index idx_articles_title_hash — no table I/O.

        Pass a pooled ``conn`` for per-worker parallel queries.
        """
        if not hashes:
            return set()
        if conn is not None:
            rows = await conn.fetch(
                "SELECT title_hash FROM gm_articles WHERE title_hash = ANY($1::text[])",
                hashes,
            )
        else:
            async with self._acquire() as c:
                rows = await c.fetch(
                    "SELECT title_hash FROM gm_articles WHERE title_hash = ANY($1::text[])",
                    hashes,
                )
        return {r["title_hash"] for r in rows}

    async def fetch_pending_enrichment(self, limit: int, enrich_try: int = 0) -> list[dict]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT a.id_article, a.id_source, a.url, a.author,
                       a.description, a.content, a."urlToImage",
                       a.enrich_try,
                       s.name AS source_name
                FROM gm_articles a
                LEFT JOIN gm_sources s ON s.id_source = a.id_source
                WHERE a.is_enriched = 0
                  AND a.enrich_try = $1
                  AND a.enrich_try <= 2
                  AND a.url IS NOT NULL AND a.url != ''
                  AND (s.fetch_blocked IS NULL OR s.fetch_blocked != 1)
                ORDER BY a.published_at_gmt DESC
                LIMIT $2
                """,
                enrich_try, limit,
            )
        return [_row_to_dict(r) for r in rows]

    async def mark_enrich_attempt_failed(self, article_id: str, current_try: int) -> None:
        if current_try >= 2:
            async with self._acquire() as conn:
                await conn.execute(
                    "UPDATE gm_articles SET is_enriched = -1 WHERE id_article = $1",
                    article_id,
                )
        else:
            async with self._acquire() as conn:
                await conn.execute(
                    "UPDATE gm_articles SET enrich_try = enrich_try + 1 WHERE id_article = $1",
                    article_id,
                )

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
        async with self._acquire() as conn:
            await conn.execute(
                """
                UPDATE gm_articles
                SET author        = COALESCE($1, author),
                    description   = COALESCE($2, description),
                    content       = $3,
                    is_enriched   = $4,
                    "urlToImage"  = COALESCE($5, "urlToImage"),
                    is_translated = CASE WHEN $4 = 1 AND is_translated != 1 THEN 0
                                         ELSE is_translated END
                WHERE id_article = $6
                """,
                author, description, content, is_enriched, url_to_image, article_id,
            )

    async def save_enrichment_failure(self, article_id: str, has_content: bool) -> None:
        val = 1 if has_content else -1
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE gm_articles SET is_enriched=$1 WHERE id_article=$2",
                val, article_id,
            )

    async def bulk_close_blocked_source_articles(self) -> None:
        async with self._acquire() as conn:
            await conn.execute(
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

    async def bulk_give_up_exhausted_articles(self) -> int:
        async with self._acquire() as conn:
            result = await conn.execute(
                "UPDATE gm_articles SET is_enriched = -1 "
                "WHERE is_enriched = 0 AND enrich_try > 2"
            )
        return int(result.split()[-1])

    async def fetch_pending_translation(self, batch_size: int) -> list[dict]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id_article, detected_language, title, description, content
                FROM v_articles_pending_translation
                ORDER BY translate_without_enrichment DESC, inserted_at_ms DESC
                LIMIT $1
                """,
                batch_size,
            )
        return [_row_to_dict(r) for r in rows]

    async def bulk_skip_non_translatable(self) -> int:
        """
        Mark is_translated=-1 for articles whose detected_language doesn't
        require translation: NULL language, translate=0, or language not in
        the languages table.
        """
        async with self._acquire() as conn:
            result = await conn.execute(
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
        return int(result.split()[-1])

    async def save_translation(self, article_id: str, values: TranslationValues) -> None:
        _ALLOWED = frozenset({
            "is_translated", "translated_title",
            "translated_description", "translated_content",
        })
        params = {k: v for k, v in values.items() if k in _ALLOWED}
        if "is_translated" not in params:
            raise ValueError("save_translation requires 'is_translated'")
        # Build: SET col=$1, col2=$2, … WHERE id_article=$N
        keys   = [k for k in params]
        sets   = ", ".join(f"{k}=${i+1}" for i, k in enumerate(keys))
        vals   = [params[k] for k in keys] + [article_id]
        async with self._acquire() as conn:
            await conn.execute(
                f"UPDATE gm_articles SET {sets} WHERE id_article=${len(vals)}",
                *vals,
            )

    async def fetch_articles_missing_gmt(
        self, source_id: str
    ) -> list[tuple[str, str]]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id_article, "publishedAt"
                FROM gm_articles
                WHERE id_source = $1
                  AND published_at_gmt IS NULL
                  AND "publishedAt" IS NOT NULL
                """,
                source_id,
            )
        return [(r["id_article"], r["publishedAt"]) for r in rows]

    async def update_gmt_batch(self, updates: list[GmtUpdate]) -> None:
        if not updates:
            return
        async with self._acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    "UPDATE gm_articles SET published_at_gmt=$1 WHERE id_article=$2",
                    [(u["gmt_timestamp"], u["article_id"]) for u in updates],
                )

    # ═══════════════════════════════════════════════════════════════════════════
    # BLOCKED DOMAINS
    # ═══════════════════════════════════════════════════════════════════════════

    async def load_blocked_domains(self) -> list[tuple[str, int]]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT domain, blocked_count FROM gm_blocked_domains WHERE is_blocked=1"
            )
        return [(r["domain"], r["blocked_count"]) for r in rows]

    async def increment_blocked_domain(
        self, domain: str, error_code: Any = 403
    ) -> tuple[int, bool]:
        """
        Upsert blocked-domain counter.
        Returns (new_count, newly_became_blocked).
        Atomic INSERT … ON CONFLICT DO UPDATE … RETURNING replaces the
        aiosqlite _write_lock + separate SELECT.
        """
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO gm_blocked_domains (domain, blocked_count, is_blocked, last_error, updated_at)
                VALUES ($1, 1, 0, $2, now())
                ON CONFLICT(domain) DO UPDATE SET
                    blocked_count = gm_blocked_domains.blocked_count + 1,
                    last_error    = excluded.last_error,
                    updated_at    = now(),
                    is_blocked    = CASE
                        WHEN gm_blocked_domains.blocked_count + 1 >= 3 THEN 1
                        ELSE gm_blocked_domains.is_blocked
                    END
                RETURNING blocked_count, is_blocked
                """,
                domain, str(error_code),
            )
        count      = row["blocked_count"] if row else 1
        is_blocked = bool(row["is_blocked"]) if row else False
        return count, is_blocked

    async def bulk_remove_pending_for_domain(self, domain: str) -> int:
        async with self._acquire() as conn:
            result = await conn.execute(
                """
                UPDATE gm_articles SET is_enriched = -1
                WHERE is_enriched = 0
                  AND (content IS NULL OR content = '')
                  AND url LIKE $1
                """,
                f"%{domain}%",
            )
        return int(result.split()[-1])

    # ═══════════════════════════════════════════════════════════════════════════
    # QUEUE STATS
    # ═══════════════════════════════════════════════════════════════════════════

    async def fetch_queue_stats(self) -> QueueStats:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT is_enriched, is_translated, COUNT(*) AS cnt "
                "FROM gm_articles GROUP BY is_enriched, is_translated"
            )
            enrich_map: dict[int, int] = {}
            trans_map:  dict[int, int] = {}
            for r in rows:
                ie, it, cnt = r["is_enriched"], r["is_translated"], r["cnt"]
                enrich_map[ie] = enrich_map.get(ie, 0) + cnt
                trans_map[it]  = trans_map.get(it,  0) + cnt

            tier_rows = await conn.fetch(
                "SELECT enrich_try, COUNT(*) AS cnt FROM gm_articles "
                "WHERE is_enriched = 0 GROUP BY enrich_try"
            )
            tier_map = {r["enrich_try"]: r["cnt"] for r in tier_rows}

            tp_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt FROM gm_articles
                WHERE is_translated = 0
                  AND is_enriched IN (1, -1)
                  AND detected_language IN (
                      SELECT language_code FROM languages WHERE translate = 1
                  )
                """
            )

        return {
            "enriched":          enrich_map.get(1,  0),
            "enrich_pending":    enrich_map.get(0,  0),
            "enrich_failed":     enrich_map.get(-1, 0),
            "translated":        trans_map.get(1,   0),
            "translate_skipped": trans_map.get(-1,  0),
            "translate_pending": tp_row["cnt"] if tp_row else 0,
            "pending_by_tier":   tier_map,
            "refreshed_at":      int(time.time() * 1000),
        }

    @property
    def cached_stats(self) -> QueueStats:
        return self._cached_stats

    async def refresh_stats_cache(self) -> QueueStats:
        stats = await self.fetch_queue_stats()
        self._cached_stats = stats
        return stats

    async def fetch_article_stats(self) -> ArticleStats:
        now_ms = int(time.time() * 1000)
        async with self._acquire() as conn:
            total        = (await conn.fetchval("SELECT COUNT(*) FROM gm_articles")) or 0
            last_24h     = (await conn.fetchval(
                "SELECT COUNT(*) FROM gm_articles WHERE inserted_at_ms > $1",
                now_ms - 86_400_000,
            )) or 0
            last_hour    = (await conn.fetchval(
                "SELECT COUNT(*) FROM gm_articles WHERE inserted_at_ms > $1",
                now_ms - 3_600_000,
            )) or 0
            total_sources = (await conn.fetchval("SELECT COUNT(*) FROM gm_sources")) or 0
        return {
            "total":         total,
            "last_24h":      last_24h,
            "last_hour":     last_hour,
            "total_sources": total_sources,
            "timestamp":     now_ms,
        }

    async def fetch_pending_by_language(self, limit: int = 10) -> list[dict]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT detected_language, language_name, target_language, COUNT(*) AS n
                FROM v_articles_pending_translation
                GROUP BY detected_language, language_name, target_language
                ORDER BY n DESC
                LIMIT $1
                """,
                limit,
            )
        return [_row_to_dict(r) for r in rows]
