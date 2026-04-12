"""
db_factory.py — Selects the appropriate NewsDatabase backend based on .env.

.env options
------------
DB_BACKEND=sqlite          (default) — uses news_db.py  + DB_PATH
DB_BACKEND=postgresql               — uses news_db_pg.py + DATABASE_URL

Usage
-----
    from db_factory import get_db_class, get_db_dsn, get_db_backend

    cls = get_db_class()          # NewsDatabase class (sqlite or pg variant)
    dsn = get_db_dsn()            # file path  OR  postgresql:// DSN
    db  = await cls.open(dsn)     # identical API for both
"""

from __future__ import annotations

import os
import logging
from typing import TYPE_CHECKING

from decouple import config, UndefinedValueError

if TYPE_CHECKING:
    from news_db import NewsDatabase   # type: ignore[assignment]

logger = logging.getLogger(__name__)


def get_db_backend() -> str:
    """Return 'sqlite' or 'postgresql' (normalised, trimmed, lower-cased)."""
    return str(config("DB_BACKEND", default="sqlite", cast=str)).strip().lower()


def get_db_dsn() -> str:
    """
    Return the connection string for the configured backend.

    sqlite     → absolute path to .db file (resolved from DB_PATH)
    postgresql → postgresql:// DSN from DATABASE_URL (never logged in full)
    """
    backend = get_db_backend()
    if backend == "postgresql":
        try:
            dsn = str(config("DATABASE_URL", cast=str)).strip()
        except UndefinedValueError:
            raise RuntimeError(
                "DB_BACKEND=postgresql but DATABASE_URL is not set in .env"
            )
        if not dsn.startswith("postgresql"):
            raise ValueError(
                f"DATABASE_URL must start with 'postgresql://' (got: {dsn[:20]}…)"
            )
        # Log only the host/db part — never the credentials
        try:
            safe = dsn.split("@", 1)[1] if "@" in dsn else dsn.split("://", 1)[1]
        except Exception:
            safe = "<postgresql>"
        logger.info(f"🗄️  DB backend: PostgreSQL @ {safe}")
        return dsn

    # Default: SQLite
    db_path = str(config("DB_PATH", default="predator_news.db", cast=str)).strip()
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    logger.info(f"🗄️  DB backend: SQLite @ {db_path}")
    return db_path


def get_db_class():
    """
    Return the NewsDatabase class appropriate for the configured backend.

    Imports are deferred so that projects using only one backend don't need
    the other backend's driver installed.
    """
    backend = get_db_backend()
    if backend == "postgresql":
        try:
            import asyncpg  # noqa: F401 — verify driver is installed
        except ImportError:
            raise RuntimeError(
                "DB_BACKEND=postgresql requires 'asyncpg'.  "
                "Install it with: pip install asyncpg"
            )
        from news_db_pg import NewsDatabase as _PG
        return _PG

    from news_db import NewsDatabase as _SQLite
    return _SQLite
