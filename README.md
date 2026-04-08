# wxNews - Real-Time News Aggregation System

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Modern async news aggregation system with FastAPI backend, SQLite database, and wxPython GUI. Collects news from NewsAPI, RSS feeds, and MediaStack with automatic timezone detection, full-text content enrichment via headless browser fallback, and a real-time wxPython GUI reader.

---

## 🚀 Quick Start

### Start the System

```bash
# Start the unified collector + API service (systemd)
sudo systemctl start wxAsyncNewsGather.service

# Check status
sudo systemctl status wxAsyncNewsGather.service

# Restart
sudo systemctl restart wxAsyncNewsGather.service

# Start the GUI reader
python wxAsyncNewsReaderv6.py
```

### Stop the System

```bash
sudo systemctl stop wxAsyncNewsGather.service
```

---

## 📋 Overview

**wxNews** is a comprehensive news aggregation system that:

- ✅ Collects news from **NewsAPI**, **RSS feeds**, and **MediaStack**
- ✅ Runs as **systemd service** with FastAPI backend
- ✅ Stores data in **SQLite** with efficient indexing
- ✅ Provides **REST API** for real-time article queries
- ✅ Features **modern wxPython GUI** with source filtering
- ✅ Supports **automatic timezone detection** (96.5% coverage)
- ✅ Fetches **full article content** via Playwright headless browser fallback
- ✅ Handles **deduplication** by URL
- ✅ Retroactively enriches historical articles via **backfill task**
- ✅ GUI reader shows full article text with **Read more** toggle

---

## 🏗️ Architecture

```text
┌───────────────────────────────────────────────────────────────┐
│              wxAsyncNewsGather.py (systemd)                   │
│                                                                │
│  ┌──────────────────────┐    ┌──────────────────────────┐   │
│  │  FastAPI Server      │    │  News Collectors         │   │
│  │  Port: 8765          │    │  (Parallel Tasks)        │   │
│  ├──────────────────────┤    ├──────────────────────────┤   │
│  │ • GET /api/articles  │    │ • NewsAPI (4 languages)  │   │
│  │ • GET /api/sources   │    │ • RSS Feeds (480+ srcs)  │   │
│  │ • GET /api/stats     │    │ • MediaStack (7500+ src) │   │
│  │ • GET /api/health    │    │ • Backfill (265k+ arts)  │   │
│  │ • GET /docs          │    │                          │   │
│  └──────────────────────┘    │ Cycles: 10-30min         │   │
│              │                └──────────────────────────┘   │
│              └──────────┬────────────────┘                    │
│                         ▼                                     │
│              ┌─────────────────────┐                          │
│              │  predator_news.db   │                          │
│              │  (SQLite Database)  │                          │
│              │  • gm_articles      │                          │
│              │  • gm_sources       │                          │
│              │  • gm_newsapi_src   │                          │
│              └─────────────────────┘                          │
└───────────────────────────────────────────────────────────────┘
                         ▲
                         │ HTTP API
                         │ Polling (30s)
                         │
              ┌──────────────────────┐
              │ wxAsyncNewsReaderv6  │
              │  (wxPython GUI)      │
              │                      │
              │ • Notebook UI        │
              │ • Source CheckList   │
              │ • Article Browser    │
              │ • Auto-refresh       │
              └──────────────────────┘
```

---

## 📦 Components

### 1. **wxAsyncNewsGather.py** (Backend Service — ARQUIVO PRINCIPAL)

> ⚠️ **IMPORTANTE**: O serviço systemd é chamado `wxAsyncNewsGather.service` mas executa o arquivo **`wxAsyncNewsGather.py`**.
> O arquivo `wxAsyncNewsGatherAPI.py` é legado e **não é mais utilizado**.

**Purpose**: Unified async service running news collection, content backfill, translation, and FastAPI server in a single process

**Features**:

- Runs **six parallel tasks**:
  - NewsAPI (4 languages)
  - RSS Feeds (480+ sources)
  - MediaStack (7,500+ sources)
  - Content backfill (`backfill_content`)
  - Translation backfill (`backfill_translations`)
  - FastAPI server (port 8765)
- Provides **REST API** on port 8765 via built-in FastAPI server
- Automatic Swagger documentation at `/docs`
- Systemd service with auto-restart
- Playwright headless browser fallback for JS-rendered pages and bot-blocking (403/406)

**Configuration**: `/etc/systemd/system/wxAsyncNewsGather.service`

**Logs**: `journalctl -u wxAsyncNewsGather.service -f`

---

### 2. **wxAsyncNewsReaderv6.py** (GUI Client)

**Purpose**: Modern desktop interface for browsing collected news

**Features**:

- **wx.Notebook** interface with multiple tabs
- **CheckListBox** for source selection (480+ sources)
- Real-time polling via FastAPI (30-second intervals)
- HTML article rendering with wx.html2
- Auto-refresh on source selection changes
- Select All / Deselect All / Load Checked buttons
- Article cards show **full content** with collapsible "Read more" toggle (when RSS description < 200 chars)
- Article images (`urlToImage`) displayed in every card

**API Connection**: Polls `http://localhost:8765/api/articles`

**Startup**:

```bash
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate
python wxAsyncNewsReaderv6.py
```

---

### 3. **predator_news.db** (SQLite Database)

**Tables**:

- `gm_articles` - Collected news articles (~55k+)
- `gm_sources` - News source catalog (480+ sources)
- `gm_newsapi_sources` - NewsAPI source registry

**Key Article Fields**:

- `id_article` - Primary key
- `title`, `description`, `url`, `author`
- `published_at` - Original timestamp (string)
- `published_at_gmt` - Normalized GMT timestamp (Unix epoch)
- `inserted_at_ms` - Millisecond insertion timestamp
- `content` - Full article text (up to 50,000 chars, all paragraphs)
- `urlToImage` - Article image URL (extracted from RSS if not provided)
- `id_source` - Source tracking
- `use_timezone` - Timezone detection flag

**Database Location**: `/home/jamaj/src/python/pyTweeter/predator_news.db`

---

## 🔧 Installation & Configuration

### Prerequisites

- Python 3.10 or higher
- SQLite 3
- wxPython 4.2+
- FastAPI + Uvicorn

### Install Dependencies

```bash
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate

# Install FastAPI dependencies
pip install -r requirements-fastapi.txt

# Or full requirements
pip install -r requirements.txt
```

### Environment Configuration

Create or edit `.env` file:

```bash
# NewsAPI Keys (get from https://newsapi.org)
NEWS_API_KEY_1=your_key_here
NEWS_API_KEY_2=your_key_here

# MediaStack Key (optional)
MEDIASTACK_API_KEY=your_key_here

# Database
DB_PATH=predator_news.db

# API Configuration
NEWS_API_URL=http://localhost:8765
NEWS_API_PORT=8765
NEWS_API_HOST=0.0.0.0
NEWS_POLL_INTERVAL_MS=30000
API_SERVER_ENABLED=true

# Update Intervals (seconds)
NEWSAPI_CYCLE_INTERVAL=600
RSS_CYCLE_INTERVAL=900
MEDIASTACK_CYCLE_INTERVAL=3600

# Content Enrichment
ENRICH_MISSING_CONTENT=true
ENRICH_TIMEOUT=10

# Backfill (retroactive content enrichment)
BACKFILL_ENABLED=true
BACKFILL_BATCH_SIZE=20
BACKFILL_DELAY=3.0
BACKFILL_CYCLE_INTERVAL=1800
```

### Install Systemd Service

```bash
# Install Playwright Chromium (for headless browser content fetching)
pip install playwright
playwright install chromium

# Copy service file
sudo cp wxAsyncNewsGather.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable on boot
sudo systemctl enable wxAsyncNewsGather.service

# Start service
sudo systemctl start wxAsyncNewsGather.service

# Check status
sudo systemctl status wxAsyncNewsGather.service
```

---

## 📚 Usage

### Service Management

```bash
# Start service
sudo systemctl start wxAsyncNewsGather.service

# Stop service
sudo systemctl stop wxAsyncNewsGather.service

# Restart service
sudo systemctl restart wxAsyncNewsGather.service

# View logs (real-time)
journalctl -u wxAsyncNewsGather.service -f

# View last 50 log lines
journalctl -u wxAsyncNewsGather.service -n 50

# View errors only
journalctl -u wxAsyncNewsGather.service -p err
```

### API Endpoints

**Base URL**: `http://localhost:8765`

| Endpoint | Method | Description |
| ---------- | ------ | ----------- |
| `/` | GET | API information |
| `/docs` | GET | Interactive Swagger UI |
| `/api/health` | GET | Health check |
| `/api/articles` | GET | Query articles since timestamp |
| `/api/latest_timestamp` | GET | Get latest insertion timestamp |
| `/api/sources` | GET | List available sources |
| `/api/stats` | GET | Collection statistics |

**Example API Call**:

```bash
# Get articles since timestamp
curl "http://localhost:8765/api/articles?since=1710000000000&limit=50"

# Get health status
curl http://localhost:8765/api/health

# Get sources
curl http://localhost:8765/api/sources
```

### Database Queries

```bash
# Count total articles
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles;"

# Recent articles (last 10)
sqlite3 predator_news.db "
SELECT datetime(published_at_gmt, 'unixepoch') as date, 
       title, 
       source_name 
FROM gm_articles 
ORDER BY published_at_gmt DESC 
LIMIT 10;"

# Articles by source (last 24h)
sqlite3 predator_news.db "
SELECT source_name, COUNT(*) as total 
FROM gm_articles 
WHERE published_at_gmt > unixepoch('now', '-1 day')
GROUP BY source_name 
ORDER BY total DESC 
LIMIT 20;"

# Sources with timezone enabled
sqlite3 predator_news.db "
SELECT source_name, timezone, use_timezone 
FROM gm_sources 
WHERE use_timezone = 1 
ORDER BY source_name;"
```

---

## 🌍 Timezone System

**Coverage**: 96.5% of articles have `published_at_gmt` populated

**Detection Methods** (in order):

1. **RFC-5322 Header**: `Date:` header from RSS feed
2. **pubDate Tag**: `<pubDate>` with timezone in XML
3. **X-Powered-By**: Server header analysis
4. **Manual Fallback**: Configured in `gm_sources.timezone`

**Verification**:

```bash
python check_gmt_coverage.py
```

See [docs/USE_TIMEZONE_SYSTEM.md](docs/USE_TIMEZONE_SYSTEM.md) for details.

---

## 📊 Features

### News Collection

- **NewsAPI**: Top headlines in EN, PT, ES, IT (4 API keys)
- **RSS Feeds**: 480+ curated sources (news + tech blogs)
- **MediaStack**: 7,500+ global news sources (free tier)

### Content Enrichment

- Full article content fetching via `requests` + BeautifulSoup
- **Playwright headless Chromium fallback** for JS-rendered pages and 403/406 bot-blocking
- Full text extraction up to 50,000 characters (all paragraphs, no hard cap)
- Image URL extraction from `urlToImage` field or from RSS `<img>` tags in description
- HTML description parsing and sanitization
- Automatic deduplication by URL
- **Backfill task**: retroactively enriches articles with missing content (batch=20, every 30 min)

### API Features

- Timestamp-based queries (`inserted_at_ms`)
- Source filtering (comma-separated IDs)
- Pagination (limit parameter)
- Data integrity protection (no future timestamps)
- Interactive documentation (FastAPI Swagger)

### GUI Features

- Multi-tab interface
- Source filtering with CheckListBox (781+ sources)
- Real-time API polling (30s intervals)
- HTML content rendering with article images
- Article cards show full content with collapsible "Read more" toggle
- Article detail viewer (opens URL in embedded browser)
- Browser integration

---

## 🔍 Troubleshooting

### Service Not Starting

```bash
# Check logs
journalctl -u wxAsyncNewsGather.service -n 100

# Check if port is in use
sudo lsof -i :8765

# Verify environment file
cat .env | grep -v '^#'

# Test manual start
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate
python wxAsyncNewsGather.py
```

### GUI Not Connecting

```bash
# Verify API is running
curl http://localhost:8765/api/health

# Check NEWS_API_URL in .env
grep NEWS_API_URL .env

# Test with browser
firefox http://localhost:8765/docs
```

### No New Articles

```bash
# Check collector logs
journalctl -u wxAsyncNewsGather.service -f | grep "Collected"

# Verify API keys
python -c "from decouple import config; print('Key 1:', config('NEWS_API_KEY_1')[:10])"

# Check last collection time
sqlite3 predator_news.db "
SELECT datetime(MAX(inserted_at_ms)/1000, 'unixepoch') as last_insert 
FROM gm_articles;"
```

### Database Issues

```bash
# Check database integrity
sqlite3 predator_news.db "PRAGMA integrity_check;"

# Check table schema
sqlite3 predator_news.db ".schema gm_articles"

# Rebuild indexes
sqlite3 predator_news.db "REINDEX;"
```

---

## 📖 Documentation

- [copilot-instructions.md](copilot-instructions.md) - System operation guide
- [FASTAPI_DOCUMENTATION.md](FASTAPI_DOCUMENTATION.md) - FastAPI architecture details
- [FASTAPI_README.md](FASTAPI_README.md) - FastAPI migration summary
- [docs/README.md](docs/README.md) - Technical documentation index
- [docs/NEWS_QUICK_START.md](docs/NEWS_QUICK_START.md) - Beginner's guide
- [docs/USE_TIMEZONE_SYSTEM.md](docs/USE_TIMEZONE_SYSTEM.md) - Timezone documentation
- [docs/SQLITE_MIGRATION.md](docs/SQLITE_MIGRATION.md) - Database migration guide
- [POLLING_TESTING_GUIDE.md](POLLING_TESTING_GUIDE.md) - API polling testing

---

## 🛠️ Development

### Run Manually (Development Mode)

```bash
# Run the unified collector + API server
python wxAsyncNewsGather.py

# Run the GUI reader
python wxAsyncNewsReaderv6.py
```

### Run Tests

```bash
# Test FastAPI endpoints
curl http://localhost:8765/api/health
curl "http://localhost:8765/api/articles?since=0&limit=5"

# Test database
python test_db_sanitize.py
```

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Run with verbose output
python wxAsyncNewsGather.py 2>&1 | tee collector.log

# Watch live logs from systemd service
journalctl -u wxAsyncNewsGather.service -f
```

---

## 📈 Statistics

- **Articles**: ~509,000+
- **Sources**: 781+
- **Languages**: English, Portuguese, Spanish, Italian
- **Timezone Coverage**: 96.5%
- **Update Frequency**: 10-30 minutes (depending on source)
- **API Response Time**: <100ms (typical)
- **Backfill**: processes 20 articles per batch, every 30 minutes

---

## 🗂️ Project Structure

```text
pyTweeter/
├── wxAsyncNewsGather.py          # 🚀 Main service (Collector + FastAPI + Backfill)
├── wxAsyncNewsGather.service     # ⚙️  Systemd service file
├── wxAsyncNewsReaderv6.py        # 🖥️  GUI application (News Feed reader)
├── wxAsyncNewsReader.py          # 🖥️  Classic GUI application (with auto-enrichment)
├── article_fetcher.py            # 📄 Content fetcher (requests + Playwright fallback)
├── predator_news.db              # 💾 SQLite database
├── .env                          # 🔐 Configuration
├── requirements-fastapi.txt      # 📦 FastAPI dependencies
├── requirements.txt              # 📦 All dependencies
├── copilot-instructions.md       # 📘 Operations guide
├── README.md                     # 📖 This file
└── docs/                         # 📚 Documentation
    ├── README.md
    ├── FASTAPI_DOCUMENTATION.md
    ├── USE_TIMEZONE_SYSTEM.md
    ├── SQLITE_MIGRATION.md
    └── [28 more .md files]
```

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

---

## 📄 License

MIT License - see LICENSE file for details

---

## 👤 Author

### jamaj

- GitHub: [@jamaj69](https://github.com/jamaj69)
- Project: wxNews (previously pyTweeter)

---

## 🙏 Acknowledgments

- **NewsAPI.org** - News aggregation API
- **MediaStack** - Global news data
- **FastAPI** - Modern async web framework
- **wxPython** - GUI framework
- **SQLAlchemy** - Database ORM

---

## 📝 Changelog

### March 31, 2026

#### `wxAsyncNewsGather.py` — Unified Backend

- ✅ **Merged FastAPI server** into the collector process — `wxAsyncNewsGatherAPI.py` retired
  - `serve_api()` coroutine runs as a 5th parallel async task
  - All endpoints (`/api/articles`, `/api/health`, `/api/sources`, `/api/stats`, `/api/latest_timestamp`) preserved
  - Single process now handles collection + backfill + API; reduced RAM from ~1GB to ~170MB
- ✅ **Fixed backfill `urlToImage` erasure bug** — SELECT now includes `urlToImage` column; UPDATE only writes it when a new value is found; 20,030 affected articles repaired in DB
- ✅ **Added `backfill_content()` async task** — retroactively enriches 265k+ articles with missing content
  - Configurable via `.env`: `BACKFILL_ENABLED`, `BACKFILL_BATCH_SIZE`, `BACKFILL_DELAY`, `BACKFILL_CYCLE_INTERVAL`

#### `article_fetcher.py` — Content Fetcher

- ✅ **Playwright headless Chromium fallback** for JS-rendered pages and 403/406 bot-blocking errors
- ✅ **Removed 5-paragraph extraction cap** — `_extract_content()` now returns up to 50,000 characters (all paragraphs)

#### `wxAsyncNewsReaderv6.py` — GUI Reader

- ✅ **Fixed blank feed on startup** — `article.get('content')` was failing on SQLAlchemy Row objects; now uses index access `article[8]`
- ✅ **Article cards show full content** with collapsible "Read more / Read less" toggle when RSS description < 200 chars
- ✅ **Article images displayed** in every card (`urlToImage` field)
- ✅ Applied content display logic to both `BuildMultiSourceArticlesHTML` and `GenerateArticleCardHTML`

#### `wxAsyncNewsReader.py` — Classic GUI Reader

- ✅ **Auto-enrich articles on open** — background thread fetches full content silently
- ✅ **Persists enriched content to database** via SQLAlchemy UPDATE
- ✅ "Enrich Content" button always visible when article has URL

### March 17, 2026

- ✅ Migrated to FastAPI from Flask
- ✅ Added systemd service (`wxAsyncNewsGatherAPI`)
- ✅ Improved timezone detection (96.5% coverage)
- ✅ Added `inserted_at_ms` timestamp for efficient queries
- ✅ Migrated from PostgreSQL to SQLite
- ✅ Updated GUI to wxAsyncNewsReaderv6
- ✅ Added API polling with real-time updates (30s interval)

### Previous

- ❌ Removed Twitter integration (API deprecated)
- ✅ Consolidated to single database (SQLite)
- ✅ Added content enrichment
- ✅ Improved error handling

---

## 🔗 Related Projects

- [NewsAPI](https://newsapi.org/) - News API provider
- [MediaStack](https://mediastack.com/) - News API aggregator
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [wxPython](https://wxpython.org/) - GUI toolkit

---

**Last Updated**: March 31, 2026
