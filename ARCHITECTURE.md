# wxNews — Architecture Reference

> Last updated: April 2026  
> Use this document as the primary guide when resuming development or debugging.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Module Map](#2-module-map)
3. [IPC Fetcher Subsystem](#3-ipc-fetcher-subsystem)
4. [Translation Subsystem](#4-translation-subsystem)
5. [Language Detection](#5-language-detection)
6. [Data Flow — Article Collection](#6-data-flow--article-collection)
7. [Database Schema](#7-database-schema)
8. [Source Blocking Logic](#8-source-blocking-logic)
9. [Debug Playbook](#9-debug-playbook)
10. [Extending the System](#10-extending-the-system)

---

## 1. System Overview

```
                    ┌─────────────────────────────────────────────────────┐
                    │         wxAsyncNewsGather.py  (systemd service)     │
                    │                                                     │
                    │  asyncio tasks running in parallel:                 │
                    │  ┌──────────────┐  ┌──────────────┐               │
                    │  │  FastAPI     │  │  RSS Collector│               │
                    │  │  :8765       │  │  (480+ feeds) │               │
                    │  └──────────────┘  └──────┬───────┘               │
                    │  ┌──────────────┐          │                       │
                    │  │  NewsAPI     │  ┌───────▼───────┐               │
                    │  │  (4 langs)   │  │  Backfill     │               │
                    │  └──────────────┘  │  Content      │               │
                    │  ┌──────────────┐  └───────┬───────┘               │
                    │  │  MediaStack  │          │                       │
                    │  │  (7500+ src) │  ┌───────▼───────┐               │
                    │  └──────────────┘  │  Backfill     │               │
                    │                    │  Translations │               │
                    │                    └───────┬───────┘               │
                    └────────────────────────────┼────────────────────────┘
                                                 │ SQLite
                                         ┌───────▼────────┐
                                         │ predator_news  │
                                         │     .db        │
                                         └───────┬────────┘
                                                 │ REST API :8765
                                         ┌───────▼────────┐
                                         │ wxAsyncNews    │
                                         │ Readerv6.py    │
                                         │ (wxPython GUI) │
                                         └────────────────┘
```

The service is a **single Python process** running several `asyncio` tasks concurrently. Subprocesses are used only for the HTTP fetcher backends and the translation models (both via `multiprocessing.Queue` IPC).

---

## 2. Module Map

| File | Role | Spawns subprocesses? |
|------|------|----------------------|
| `wxAsyncNewsGather.py` | Main service: FastAPI + collectors + backfill + translation orchestration | No |
| `article_fetcher.py` | **IPC orchestrator** for article content fetching | Yes (3 workers) |
| `cffi_worker.py` | Subprocess worker — `curl_cffi` Chrome TLS impersonation | — (is a worker) |
| `requests_worker.py` | Subprocess worker — `requests` with browser headers | — (is a worker) |
| `playwright_worker.py` | Subprocess worker — headless Chromium via Playwright | — (is a worker) |
| `translatev1.py` | IPC orchestrator for translation (reference pattern) | Yes (per translator) |
| `google_worker.py` | Subprocess worker — Google Translate | — (is a worker) |
| `nllb_worker.py` | Subprocess worker — NLLB offline model | — (is a worker) |
| `language_service.py` | Language detection helpers | No |
| `lang_rules.py` | Rule-based language overrides and filter list | No |
| `async_tickdb.py` | Async scheduler (tick-based task runner) | No |
| `html_utils.py` | HTML sanitization utilities | No |
| `text_utils.py` | Text normalization helpers | No |
| `wxAsyncNewsReaderv6.py` | wxPython GUI client | No |
| `predator_news.db` | SQLite database | — |

### Legacy / unused files

| File | Status |
|------|--------|
| `wxAsyncNewsGatherAPI.py` | **Legacy** — not run by systemd, superseded by `wxAsyncNewsGather.py` |
| `wxAsyncNewsGather.service` (archive/) | Old service file |

---

## 3. IPC Fetcher Subsystem

This is the main architectural feature introduced in April 2026. All HTTP fetching for article content enrichment is isolated into **three persistent subprocesses**, each communicating with the orchestrator via `multiprocessing.Queue`.

### Architecture diagram

```
article_fetcher.py  (orchestrator, runs in main process)
│
├── _CffiFetcher  ──spawn──▶  cffi_worker.worker()  (subprocess)
│       req_q ──(req_id, url, timeout)──▶
│       resp_q ◀──(req_id, result_dict)──
│
├── _RequestsFetcher  ──spawn──▶  requests_worker.worker()  (subprocess)
│       req_q ──(req_id, url, timeout)──▶
│       resp_q ◀──(req_id, result_dict)──
│
└── _PlaywrightFetcher  ──spawn──▶  playwright_worker.worker()  (subprocess)
        req_q ──(req_id, url, timeout)──▶
        resp_q ◀──(req_id, result_dict)──
```

Subprocesses are started **lazily** on the first request and kept alive for the lifetime of the service (singletons `_cffi`, `_requests`, `_playwright` at module level). `atexit` handlers call `shutdown()` automatically.

### Wire protocol

```
Request  (orchestrator → worker):
    (req_id: str, url: str, timeout: int)
    or None  ← shutdown sentinel

Response (worker → orchestrator):
    (req_id: str, result: dict)

result dict:
    {
        'html':       str | None,
        'success':    bool,
        'error_code': int | str | None,   # HTTP status code or 'TIMEOUT'/'CONNECTION_ERROR'/...
        'error_type': 'permanent' | 'temporary' | None
    }
```

### Error classification

| HTTP codes | `error_type` | Meaning |
|------------|-------------|---------|
| 401, 402, 403, 404, 406, 410, 451 | `permanent` | Paywall, forbidden, gone — increment blocked_count |
| 429, 500, 502, 503, 504 | `temporary` | Rate limit / server error — retry later |
| Timeout, ConnectionError | `temporary` | Network blip |
| `UNAVAILABLE` | `temporary` | Library not installed (cffi fallback) |

> **Important**: only `error_type == 'permanent'` increments `gm_sources.blocked_count`. Temporary failures do not.

### `_ProcessFetcher` base class

Lives in `article_fetcher.py`. Provides:

- `start()` / `_ensure_started()` — lazy subprocess launch + pump thread
- `_pump_responses()` — daemon thread that reads `resp_q` and dispatches results to waiting callers
- `shutdown()` — sends sentinel, joins process and pump thread, cancels pending futures
- `fetch_sync(url, timeout)` — blocking call (uses `threading.Event`)
- `fetch_async(url, timeout)` — non-blocking call (uses `asyncio.Future`); updates `self._loop` to the running loop on first async call

Subclasses override only `_make_process(ctx, req_q, resp_q)`.

### Orchestration logic in `ArticleContentFetcher.fetch()`

```
1. sanitize URL  (redirect chain stripping, double-slash fix)
2. validate URL  (must start with http:// or https://)
3. try cffi worker (primary)
   → if cffi UNAVAILABLE, try requests worker instead
4. Playwright fallback if:
     a. primary error_code in {403, 406}  (bot-block, bypass with real browser)
     b. primary was not successful AND error_type == 'temporary'
     c. primary succeeded but HTML has < 2 real paragraphs (JS skeleton)
5. parse best HTML with BeautifulSoup (lxml → html.parser fallback)
6. extract: author, published_time, description, content
7. return result dict
```

### Module-level singletons and public API

```python
# article_fetcher.py

# Singletons (started lazily, live for process lifetime)
_cffi       = _CffiFetcher()
_requests   = _RequestsFetcher()
_playwright = _PlaywrightFetcher()

# Eagerly start all workers at service startup (optional, avoids first-call latency)
start_all()

# Graceful shutdown (called automatically via atexit)
shutdown_all()

# Main public API used by wxAsyncNewsGather and enrichment_worker
fetch_article_content(url, timeout=10)  →  dict

# Class API (used internally by fetch_article_content)
ArticleContentFetcher(timeout=10).fetch(url)  →  dict
ArticleContentFetcher.sanitize_url(url)  →  str  (static, used in wxAsyncNewsGather)
```

### Worker files summary

| File | Library | Notes |
|------|---------|-------|
| `cffi_worker.py` | `curl_cffi` | Chrome TLS fingerprint (JA3/JA4), bypasses Cloudflare. Gracefully returns `UNAVAILABLE` if not installed. |
| `requests_worker.py` | `requests` | Browser-like headers. Special `FeedReader` User-Agent for `ndtvprofit.com`. |
| `playwright_worker.py` | `playwright` | Headless Chromium, `--blink-settings=imagesEnabled=false` (no `page.route()` — avoids `CancelledError` on navigation timeout). |

Each worker is **self-contained**: imports happen inside `worker()` or `_fetch()`, error-type constants are mirrored locally. No import from `article_fetcher`.

---

## 4. Translation Subsystem

Same IPC pattern, defined in `translatev1.py`. Reference architecture for the fetcher subsystem.

```
translatev1.py  (_ProcessTranslator base class)
│
├── GoogleTranslator  ──spawn──▶  google_worker.worker()
└── NLLBTranslator    ──spawn──▶  nllb_worker.worker()
```

Workers accept `(req_id, text, src_lang, tgt_lang)` requests and respond with `(req_id, translated_text)`.

`wxAsyncNewsGather.py` creates translator instances and calls `translate_sync()` / `translate_async()`.

---

## 5. Language Detection

Language detection runs **in the main process** (no subprocess), inside `wxAsyncNewsGather.py`.

### Detection flow (`detect_article_language()`)

1. `langdetect.detect_langs(text)` — returns list of `(lang, probability)` sorted by confidence
2. If the top result is a **low-prior language** (`cy`, `mt`, `la`, `af`, `so`) with probability < 0.90, use the second candidate instead
3. Threshold 0.90 prevents Welsh (`cy`) and other short-text false-positives on English/Spanish content

```python
_LANGDETECT_LOW_PRIOR_LANGS = frozenset({'cy', 'mt', 'la', 'af', 'so'})
_LOW_PRIOR_MIN_PROB = 0.90
```

This fix was introduced in March 2026 after `cy` was being assigned to English/Spanish articles.

---

## 6. Data Flow — Article Collection

```
RSS Feed (feedparser)
    │
    ▼
parse_entry()  →  deduplicate by URL  →  INSERT gm_articles
    │                                    (description from RSS, no content yet)
    ▼
backfill_content()  (runs every 30 min, batch=20)
    │
    ▼
fetch_article_content(url)           ← article_fetcher.py
    │
    ├── cffi_worker   (subprocess)   ← primary
    ├── requests_worker (subprocess) ← if cffi unavailable
    └── playwright_worker (subprocess) ← fallback
    │
    ▼
UPDATE gm_articles SET content=..., author=..., published_time=...
    │
    ▼
backfill_translations()  (runs every N min)
    │
    ▼
translate_sync(text, src, tgt)       ← translatev1.py
    │
    ├── google_worker (subprocess)
    └── nllb_worker   (subprocess)
    │
    ▼
UPDATE gm_articles SET translated_title=..., is_translated=1
```

---

## 7. Database Schema

**File**: `predator_news.db` (SQLite)

### `gm_articles`

| Column | Type | Notes |
|--------|------|-------|
| `id_article` | INTEGER PK | |
| `title` | TEXT | Original title |
| `url` | TEXT UNIQUE | Deduplication key |
| `description` | TEXT | RSS teaser or og:description |
| `content` | TEXT | Full body text (up to 50 000 chars) |
| `author` | TEXT | Extracted from page |
| `published_at` | TEXT | Original string from feed |
| `published_at_gmt` | INTEGER | Unix epoch UTC (96.5% coverage) |
| `inserted_at_ms` | INTEGER | Millisecond insertion timestamp |
| `source_name` | TEXT | Human-readable source name |
| `id_source` | INTEGER FK → gm_sources | |
| `urlToImage` | TEXT | Article image URL |
| `detected_language` | TEXT | ISO 639-1 code (langdetect) |
| `is_translated` | INTEGER | 0 = needs translation, 1 = done |
| `translated_title` | TEXT | |
| `translated_description` | TEXT | |
| `use_timezone` | INTEGER | 1 if GMT was auto-detected |

### `gm_sources`

| Column | Type | Notes |
|--------|------|-------|
| `id_source` | INTEGER PK | |
| `source_name` | TEXT | Display name |
| `url` | TEXT | Feed URL |
| `fetch_blocked` | INTEGER | 1 = stop fetching this source |
| `blocked_count` | INTEGER | Increments on `permanent` errors only |
| `timezone` | TEXT | Fallback timezone (pytz key) |
| `use_timezone` | INTEGER | 1 = auto-detect GMT from feed headers |

> **Blocking threshold**: when `blocked_count >= 3` AND `fetch_blocked = 0`, the collector sets `fetch_blocked = 1`.  
> Only `error_type == 'permanent'` increments `blocked_count`. HTTP 5xx and timeouts do NOT.

### `languages`

Lookup table: ISO 639-1 code → full language name. Populated by `setup_languages_table.py`.

---

## 8. Source Blocking Logic

Defined in `wxAsyncNewsGather.py`, triggered after `fetch_article_content()` returns:

```python
if result.get('error_type') == ERROR_PERMANENT:
    source.blocked_count += 1
    if source.blocked_count >= 3:
        source.fetch_blocked = 1
        logger.warning("Source %s blocked after 3 permanent errors", source.source_name)
```

To **unblock all sources** manually:

```bash
sqlite3 predator_news.db "UPDATE gm_sources SET fetch_blocked=0, blocked_count=0;"
```

To check blocked sources:

```bash
python check_blocklist.py
# or:
sqlite3 predator_news.db "SELECT source_name, blocked_count FROM gm_sources WHERE fetch_blocked=1;"
```

---

## 9. Debug Playbook

### 9.1 Content fetcher not enriching articles

```bash
# Check if workers are starting (logs at DEBUG level)
journalctl -u wxAsyncNewsGather.service -f | grep -E 'cffi|requests|playwright|fetcher'

# Test fetcher directly
python article_fetcher.py https://www.reuters.com/world/

# Test individual workers
python - <<'EOF'
import multiprocessing, cffi_worker
ctx = multiprocessing.get_context('spawn')
req_q = ctx.Queue(); resp_q = ctx.Queue()
p = ctx.Process(target=cffi_worker.worker, args=(req_q, resp_q)); p.start()
req_q.put(('t1', 'https://www.reuters.com/world/', 10))
print(resp_q.get(timeout=15))
req_q.put(None); p.join()
EOF
```

### 9.2 A specific site returns `permanent` error (403/404)

```bash
# Check error type
python article_fetcher.py https://problematic-site.com/article

# If it's bot-blocked (403/406), playwright will auto-retry
# If playwright also fails with 403, the site is truly paywalled → permanent

# Check if source got blocked
sqlite3 predator_news.db \
  "SELECT source_name, fetch_blocked, blocked_count FROM gm_sources WHERE url LIKE '%site.com%';"
```

### 9.3 Playwright subprocess crashing

```bash
# Check playwright install
python -c "from playwright.sync_api import sync_playwright; print('OK')"
playwright install chromium

# Run playwright worker standalone
python playwright_worker.py  # has no __main__ — check imports only:
python -c "import playwright_worker; print('OK')"
```

### 9.4 Language detection producing wrong language codes

```bash
# Check detected_language distribution
sqlite3 predator_news.db \
  "SELECT detected_language, COUNT(*) c FROM gm_articles GROUP BY detected_language ORDER BY c DESC LIMIT 20;"

# Re-detect articles with suspect language
python redetect_article_languages.py
```

### 9.5 Queue deadlock / worker not responding

The `fetch_sync()` caller waits up to `timeout + 30` seconds then returns a `TIMEOUT` result — it does not block forever. If the worker subprocess dies, the pump thread will stop reading from `resp_q`, and callers will eventually hit the ceiling timeout.

To force-restart workers, restart the service:

```bash
sudo systemctl restart wxAsyncNewsGather.service
```

The singletons `_cffi / _requests / _playwright` are module-level — they are recreated on the next import after service restart.

### 9.6 Articles not being collected from RSS

```bash
# Run RSS diagnosis
python diagnose_feeds.py

# Check a specific feed manually
python -c "
import feedparser
f = feedparser.parse('https://feed-url-here.xml')
print('status:', f.get('status'))
print('entries:', len(f.entries))
print(f.feed.get('title', 'no title'))
"

# Check blocked sources
sqlite3 predator_news.db "SELECT source_name, fetch_blocked, blocked_count FROM gm_sources WHERE fetch_blocked=1;"

# Unblock all
sqlite3 predator_news.db "UPDATE gm_sources SET fetch_blocked=0, blocked_count=0;"
```

---

## 10. Extending the System

### Adding a new HTTP fetcher backend

1. Create `my_fetcher_worker.py` with a `worker(req_q, resp_q)` function following the same protocol as `cffi_worker.py`
2. Add a subclass in `article_fetcher.py`:
   ```python
   class _MyFetcher(_ProcessFetcher):
       _PROCESS_NAME = 'my-fetch'
       _PUMP_NAME    = 'my-pump'
       def _make_process(self, ctx, req_q, resp_q):
           return ctx.Process(target=my_fetcher_worker.worker, args=(req_q, resp_q), daemon=True)
   ```
3. Instantiate `_my = _MyFetcher()` at module level
4. Add to `start_all()` / `shutdown_all()`
5. Integrate into the orchestration logic in `ArticleContentFetcher.fetch()`

### Adding a new translation backend

Follow the same pattern in `translatev1.py` — create a new worker file and a `_ProcessTranslator` subclass.

### Adding a new API endpoint

All endpoints are defined in `wxAsyncNewsGather.py` using FastAPI decorators. The app instance is `app`. Endpoints use `async def` and call `aiosqlite` for database access.

### Adding a new RSS source

Edit `rssfeeds.conf` — one URL per line. The service re-reads the config on each RSS collection cycle, so no restart is needed for source additions.
