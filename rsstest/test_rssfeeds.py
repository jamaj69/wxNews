#!/usr/bin/env python3
"""
Test RSS sources listed in rssfeeds.conf.

The script fetches every configured feed URL, parses it with feedparser,
detects language, marks whether the feed appears to be working, and writes
results as readable JSON in the rsstest directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

import feedparser

try:
    from langdetect import detect as detect_lang
except Exception:
    detect_lang = None


WORD_RE = re.compile(r"[a-zA-Z]{2,}")
LANGUAGE_HINTS = {
    "en": {"the", "and", "for", "with", "from", "this", "that"},
    "pt": {"que", "com", "para", "uma", "por", "como", "mais"},
    "es": {"que", "con", "para", "una", "por", "como", "mas"},
    "fr": {"que", "avec", "pour", "une", "dans", "plus", "des"},
    "de": {"und", "die", "der", "das", "mit", "von", "ist"},
    "it": {"che", "con", "per", "una", "come", "piu", "della"},
}

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
BASIC_HTTP_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "max-age=0",
}


@dataclass
class Source:
    index: int
    url: str
    label: str
    raw: Dict[str, Any]


def normalize_language(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    value = value.strip().lower()
    if not value:
        return "unknown"
    for sep in ("-", "_"):
        if sep in value:
            value = value.split(sep, 1)[0]
            break
    return value or "unknown"


def heuristic_language(text: str) -> str:
    words = WORD_RE.findall(text.lower())
    if not words:
        return "unknown"
    scores = {}
    for lang, hints in LANGUAGE_HINTS.items():
        scores[lang] = sum(1 for w in words if w in hints)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "unknown"
    return best


def detect_language(parsed: Any) -> Tuple[str, str]:
    feed_lang = normalize_language(getattr(parsed.feed, "language", None))
    if feed_lang != "unknown":
        return feed_lang, "feed.language"

    text_parts: List[str] = []
    for entry in parsed.entries[:20]:
        title = entry.get("title", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        if title:
            text_parts.append(str(title))
        if summary:
            text_parts.append(str(summary))
    sample_text = " ".join(text_parts).strip()
    if not sample_text:
        return "unknown", "no_text"

    if detect_lang is not None:
        try:
            lang = normalize_language(detect_lang(sample_text))
            if lang != "unknown":
                return lang, "langdetect"
        except Exception:
            pass

    return heuristic_language(sample_text), "heuristic"


def build_http_headers(url: str) -> Dict[str, str]:
    headers = dict(BASIC_HTTP_HEADERS)
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        if parsed.netloc.endswith("indianexpress.com"):
            headers["Referer"] = "https://indianexpress.com/rss/"
        else:
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    return headers


def looks_like_feed_content_type(content_type: str) -> bool:
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


def looks_like_feed_body(text: str) -> bool:
    sample = (text or "")[:2000].lower()
    return any(tag in sample for tag in ("<?xml", "<rss", "<feed", "<rdf:rdf"))


def fetch_with_curl(url: str, timeout: int) -> Tuple[int, str, str]:
    headers = build_http_headers(url)
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
            str(timeout),
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
            timeout=timeout + 5,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "curl failed").strip())

        header_text = Path(hdr_path).read_text(encoding="latin-1", errors="replace")
        body_bytes = Path(body_path).read_bytes()

        status = 0
        content_type = ""
        # curl writes one header block per redirect; we want the final one
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
            body = body_bytes.decode(charset, errors="replace")
        except Exception:
            body = body_bytes.decode("utf-8", errors="replace")

        return status, content_type, body
    finally:
        try:
            Path(hdr_path).unlink(missing_ok=True)
        except Exception:
            pass
        try:
            Path(body_path).unlink(missing_ok=True)
        except Exception:
            pass


def parse_sources(config_path: Path) -> List[Source]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    sources: List[Source] = []
    if not isinstance(data, list):
        raise ValueError(f"Expected list in {config_path}")
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        url = item.get("url", "").strip()
        if not url:
            continue
        sources.append(
            Source(
                index=idx,
                url=url,
                label=str(item.get("label", "")),
                raw=item,
            )
        )
    return sources


async def fetch_one(
    source: Source,
    timeout_seconds: int,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "index": source.index,
        "url": source.url,
        "label": source.label,
        "working": False,
        "status": "unknown",
        "http_status": None,
        "language": "unknown",
        "language_method": "none",
        "feed_title": "",
        "entry_count": 0,
        "bozo": False,
        "bozo_exception": "",
        "error": "",
        "sample_entries": [],
    }
    def fetch_sync(url: str, timeout: int) -> Tuple[int, str, str]:
        req = urlrequest.Request(url, headers=build_http_headers(url))
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            content_type = resp.headers.get("Content-Type", "")
            charset = resp.headers.get_content_charset() or "utf-8"
            body = resp.read().decode(charset, errors="replace")
            return status, content_type, body

    try:
        status, content_type, text = await asyncio.to_thread(
            fetch_sync, source.url, timeout_seconds
        )
        result["http_status"] = status
        result["content_type"] = content_type
    except TimeoutError:
        result["status"] = "timeout"
        result["error"] = "Request timed out"
        return result
    except urlerror.HTTPError as exc:
        http_code = int(getattr(exc, "code", 0))
        if http_code == 403:
            try:
                status, content_type, text = await asyncio.to_thread(
                    fetch_with_curl, source.url, timeout_seconds
                )
                result["http_status"] = status
                result["content_type"] = content_type
                if status >= 400:
                    result["status"] = "http_error"
                    result["error"] = f"HTTP Error {status} (curl fallback)"
                    return result
            except Exception as curl_exc:
                result["status"] = "http_error"
                result["http_status"] = http_code
                result["error"] = f"{exc} | curl_fallback_error: {curl_exc}"
                return result
        else:
            result["status"] = "http_error"
            result["http_status"] = http_code
            result["error"] = str(exc)
            return result
    except urlerror.URLError as exc:
        result["status"] = "request_error"
        result["error"] = str(exc)
        return result
    except Exception as exc:
        result["status"] = "request_error"
        result["error"] = str(exc)
        return result

    if not looks_like_feed_content_type(result.get("content_type", "")) and not looks_like_feed_body(text):
        result["status"] = "invalid_content_type"
        result["error"] = f"Unexpected content type: {result.get('content_type', '')}"
        return result

    parsed = feedparser.parse(text)
    entries = list(parsed.entries)
    result["entry_count"] = len(entries)
    result["bozo"] = bool(getattr(parsed, "bozo", False))

    if getattr(parsed, "bozo_exception", None):
        result["bozo_exception"] = str(parsed.bozo_exception)

    result["feed_title"] = str(getattr(parsed.feed, "title", "") or "")
    lang, method = detect_language(parsed)
    result["language"] = lang
    result["language_method"] = method

    for entry in entries[:5]:
        result["sample_entries"].append(
            {
                "title": str(entry.get("title", "") or ""),
                "link": str(entry.get("link", "") or ""),
                "published": str(entry.get("published", entry.get("updated", "")) or ""),
            }
        )

    http_status = result["http_status"] or 0
    if http_status >= 400:
        result["status"] = "http_error"
    elif result["entry_count"] == 0:
        result["status"] = "empty_feed"
    elif result["bozo"] and result["entry_count"] == 0:
        result["status"] = "parse_error"
    else:
        result["status"] = "ok"
        result["working"] = True
    return result


async def run_test(
    config_path: Path,
    output_dir: Path,
    timeout_seconds: int,
    concurrency: int,
    limit: int,
) -> Path:
    sources = parse_sources(config_path)
    if limit > 0:
        sources = sources[:limit]
    output_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    async def run_one(src: Source) -> Dict[str, Any]:
        async with sem:
            return await fetch_one(src, timeout_seconds)

    results = await asyncio.gather(*(run_one(src) for src in sources))

    ok_count = sum(1 for r in results if r["working"])
    fail_count = len(results) - ok_count

    summary = {
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path.resolve()),
        "total_sources": len(results),
        "working_sources": ok_count,
        "failing_sources": fail_count,
        "timeout_seconds": timeout_seconds,
        "concurrency": concurrency,
    }

    payload = {
        "summary": summary,
        "results": sorted(results, key=lambda x: x["index"]),
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"rssfeeds_test_{timestamp}.json"
    latest_path = output_dir / "rssfeeds_test_latest.json"
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    latest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return report_path


def build_parser() -> argparse.ArgumentParser:
    here = Path(__file__).resolve()
    root_dir = here.parent.parent
    parser = argparse.ArgumentParser(
        description="Fetch and validate feeds from rssfeeds.conf and write readable JSON report."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=root_dir / "rssfeeds.conf",
        help="Path to rssfeeds.conf (default: ../rssfeeds.conf)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=here.parent,
        help="Directory for JSON report output (default: rsstest/)",
    )
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds")
    parser.add_argument("--concurrency", type=int, default=20, help="Max concurrent fetches")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit of feeds to test (0 means all)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.config.exists():
        raise FileNotFoundError(f"Config file not found: {args.config}")

    report = asyncio.run(
        run_test(
            config_path=args.config,
            output_dir=args.output_dir,
            timeout_seconds=args.timeout,
            concurrency=args.concurrency,
            limit=args.limit,
        )
    )
    print(f"Report written: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
