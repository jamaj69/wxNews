#!/usr/bin/env python3
"""Validate feeds from xml_feeds.txt one by one and import working feeds into SQLite."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = PROJECT_ROOT / "xml_feeds.txt"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,pt;q=0.8,es;q=0.7",
    "Cache-Control": "no-cache",
}


def get_db_path() -> Path:
    """Resolve the SQLite database path from env or project default."""
    db_path = os.getenv("DB_PATH", "predator_news.db")
    if os.path.isabs(db_path):
        return Path(db_path)
    return PROJECT_ROOT / db_path


def load_urls(path: Path) -> list[str]:
    """Read non-empty URLs from xml_feeds.txt preserving order."""
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if url and not url.startswith("#"):
            urls.append(url)
    return urls


def classify_category(url: str) -> str:
    """Infer a broad category from the feed URL."""
    url_lower = url.lower()
    if any(word in url_lower for word in ("business", "finance", "economy", "market")):
        return "business"
    if any(word in url_lower for word in ("tech", "technology", "science", "ai", "gadget")):
        return "technology"
    if any(word in url_lower for word in ("sport", "sports")):
        return "sports"
    if any(word in url_lower for word in ("world", "politic", "news")):
        return "general"
    return "general"


def normalize_name(url: str, title: str) -> str:
    """Pick a readable source name from feed metadata or the URL."""
    if title.strip():
        return title.strip()[:200]
    host = urlparse(url).netloc.replace("www.", "").strip()
    return host or url


def make_source_id(url: str) -> str:
    """Create a unique, deterministic source id for the URL."""
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "").replace(".", "-").lower()
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    return f"rss-{host}-{digest}"


def local_name(tag: str) -> str:
    """Return the local XML tag name without namespace."""
    return tag.split("}", 1)[-1].lower()


def find_first_text(element: ET.Element, names: tuple[str, ...]) -> str:
    """Find the first child text matching one of the local tag names."""
    for child in element.iter():
        if local_name(child.tag) in names and child.text and child.text.strip():
            return child.text.strip()
    return ""


def count_entries(root: ET.Element) -> int:
    """Count RSS <item> or Atom <entry> nodes."""
    total = 0
    for element in root.iter():
        if local_name(element.tag) in {"item", "entry"}:
            total += 1
    return total


def validate_feed(url: str) -> dict:
    """Fetch and validate a single RSS/Atom feed."""
    result = {
        "input_url": url,
        "final_url": url,
        "status": None,
        "content_type": "",
        "ok": False,
        "entries_count": 0,
        "name": "",
        "error": None,
        "description": "",
    }

    try:
        request = Request(url, headers=BROWSER_HEADERS)
        with urlopen(request, timeout=25) as response:
            result["status"] = getattr(response, "status", None) or response.getcode()
            result["content_type"] = response.headers.get("Content-Type", "")
            result["final_url"] = response.geturl()

            if result["status"] != 200:
                result["error"] = f"HTTP {result['status']}"
                return result

            content = response.read()

        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            result["error"] = f"parse error: {exc}"
            return result

        root_tag = local_name(root.tag)
        if root_tag not in {"rss", "feed", "rdf"}:
            result["error"] = f"unexpected root tag: {root_tag}"
            return result

        entries_count = count_entries(root)
        title = find_first_text(root, ("title",))
        description = find_first_text(root, ("description", "subtitle", "tagline"))

        if entries_count == 0 and not title:
            result["error"] = "not a valid RSS/Atom feed"
            return result

        result["ok"] = True
        result["entries_count"] = entries_count
        result["name"] = normalize_name(result["final_url"], title)
        result["description"] = description[:500]
        return result

    except TimeoutError:
        result["error"] = "timeout"
        return result
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def upsert_feed(conn: sqlite3.Connection, feed: dict) -> tuple[str, str]:
    """Insert or update a validated feed in gm_sources."""
    final_url = feed["final_url"]
    input_url = feed["input_url"]
    name = feed["name"] or urlparse(final_url).netloc
    description = feed["description"] or f"RSS Feed: {name}"
    category = classify_category(final_url)

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id_source
        FROM gm_sources
        WHERE url IN (?, ?)
        LIMIT 1
        """,
        (input_url, final_url),
    )
    row = cursor.fetchone()

    if row:
        source_id = row[0]
        cursor.execute(
            """
            UPDATE gm_sources
            SET name = ?, description = ?, url = ?, category = COALESCE(NULLIF(category, ''), ?)
            WHERE id_source = ?
            """,
            (name, description, final_url, category, source_id),
        )
        conn.commit()
        return "updated", source_id

    source_id = make_source_id(final_url)
    cursor.execute(
        """
        INSERT INTO gm_sources (id_source, name, description, url, category, language, country)
        VALUES (?, ?, ?, ?, ?, '', '')
        ON CONFLICT(id_source) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            url = excluded.url,
            category = excluded.category
        """,
        (source_id, name, description, final_url, category),
    )
    conn.commit()
    return "inserted", source_id


def main() -> int:
    urls = load_urls(FEEDS_FILE)
    db_path = get_db_path()

    print(f"Feeds file: {FEEDS_FILE}")
    print(f"Database:   {db_path}")
    print(f"Testing {len(urls)} feeds one by one...\n")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA busy_timeout = 30000")

    inserted = 0
    updated = 0
    failed = 0

    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] Testing {url}")
        result = validate_feed(url)

        if not result["ok"]:
            failed += 1
            print(
                f"  FAIL  status={result['status']} error={result['error'] or 'unknown'}"
            )
            continue

        action, source_id = upsert_feed(conn, result)
        if action == "inserted":
            inserted += 1
        else:
            updated += 1

        print(
            f"  OK    {action} {source_id} | "
            f"{result['name']} | entries={result['entries_count']}"
        )

    conn.close()

    print("\nSummary")
    print(f"  Inserted: {inserted}")
    print(f"  Updated:  {updated}")
    print(f"  Failed:   {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
