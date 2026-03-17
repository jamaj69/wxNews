# wxNews - Real-Time News Aggregation System

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Modern async news aggregation system with FastAPI backend, SQLite database, and wxPython GUI. Collects news from NewsAPI, RSS feeds, and MediaStack with automatic timezone detection and content enrichment.

---

## 🚀 Quick Start

### Start the System

```bash
# Start the collector + API service (systemd)
sudo systemctl start wxAsyncNewsGatherAPI.service

# Check status
sudo systemctl status wxAsyncNewsGatherAPI.service

# Start the GUI reader
python wxAsyncNewsReaderv6.py
```

### Stop the System

```bash
sudo systemctl stop wxAsyncNewsGatherAPI.service
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
- ✅ Fetches **full article content** when available
- ✅ Handles **deduplication** by URL

---

## 🏗️ Architecture

```
┌───────────────────────────────────────────────────────────────┐
│              wxAsyncNewsGatherAPI.py (systemd)                │
│                                                                │
│  ┌──────────────────────┐    ┌──────────────────────────┐   │
│  │  FastAPI Server      │    │  News Collectors         │   │
│  │  Port: 8765          │    │  (Parallel Tasks)        │   │
│  ├──────────────────────┤    ├──────────────────────────┤   │
│  │ • GET /api/articles  │    │ • NewsAPI (4 languages)  │   │
│  │ • GET /api/sources   │    │ • RSS Feeds (480+ srcs)  │   │
│  │ • GET /api/stats     │    │ • MediaStack (7500+ src) │   │
│  │ • GET /api/health    │    │                          │   │
│  │ • GET /docs          │    │ Cycles: 10-30min         │   │
│  └──────────────────────┘    └──────────────────────────┘   │
│              │                           │                    │
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

### 1. **wxAsyncNewsGatherAPI.py** (Backend Service)

**Purpose**: Unified FastAPI application running news collection and API server

**Features**:
- Runs three parallel collectors (NewsAPI, RSS, MediaStack)
- Provides REST API for real-time article queries
- Automatic Swagger documentation at `/docs`
- Systemd service with auto-restart
- Sharing database access between collector and API

**Configuration**: `/etc/systemd/system/wxAsyncNewsGatherAPI.service`

**Logs**: `journalctl -u wxAsyncNewsGatherAPI.service -f`

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
- `content` - Full article content (when available)
- `source_name`, `id_source` - Source tracking
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

# Update Intervals
NEWSAPI_UPDATE_INTERVAL=600
RSS_UPDATE_INTERVAL=1800
MEDIASTACK_UPDATE_INTERVAL=3600
```

### Install Systemd Service

```bash
# Copy service file
sudo cp wxAsyncNewsGatherAPI.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable on boot
sudo systemctl enable wxAsyncNewsGatherAPI.service

# Start service
sudo systemctl start wxAsyncNewsGatherAPI.service

# Check status
sudo systemctl status wxAsyncNewsGatherAPI.service
```

---

## 📚 Usage

### Service Management

```bash
# Start service
sudo systemctl start wxAsyncNewsGatherAPI.service

# Stop service
sudo systemctl stop wxAsyncNewsGatherAPI.service

# Restart service
sudo systemctl restart wxAsyncNewsGatherAPI.service

# View logs (real-time)
journalctl -u wxAsyncNewsGatherAPI.service -f

# View last 50 log lines
journalctl -u wxAsyncNewsGatherAPI.service -n 50

# View errors only
journalctl -u wxAsyncNewsGatherAPI.service -p err
```

### API Endpoints

**Base URL**: `http://localhost:8765`

| Endpoint | Method | Description |
|----------|--------|-------------|
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

- Full article content fetching (when available)
- Image URL extraction
- HTML description parsing
- Automatic deduplication by URL

### API Features

- Timestamp-based queries (`inserted_at_ms`)
- Source filtering (comma-separated IDs)
- Pagination (limit parameter)
- Data integrity protection (no future timestamps)
- Interactive documentation (FastAPI Swagger)

### GUI Features

- Multi-tab interface
- Source filtering with CheckListBox
- Real-time API polling (30s intervals)
- HTML content rendering
- Article detail viewer
- Browser integration

---

## 🔍 Troubleshooting

### Service Not Starting

```bash
# Check logs
journalctl -u wxAsyncNewsGatherAPI.service -n 100

# Check if port is in use
sudo lsof -i :8765

# Verify environment file
cat .env | grep -v '^#'

# Test manual start
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate
python wxAsyncNewsGatherAPI.py
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
journalctl -u wxAsyncNewsGatherAPI.service -f | grep "Collected"

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

### Run Manual Collection (Development Mode)

```bash
# Terminal 1: Start API only
python wxAsyncNewsGatherAPI.py

# Terminal 2: Run collector manually
python wxAsyncNewsGather.py
```

### Run Tests

```bash
# Test FastAPI endpoints
python test_fastapi_news.py

# Test API polling
python test_api_polling.py

# Test database
python test_db_sanitize.py
```

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Run with verbose output
python wxAsyncNewsGatherAPI.py 2>&1 | tee collector.log
```

---

## 📈 Statistics

- **Articles**: ~55,000+
- **Sources**: 480+
- **Languages**: English, Portuguese, Spanish, Italian
- **Timezone Coverage**: 96.5%
- **Update Frequency**: 10-30 minutes (depending on source)
- **API Response Time**: <100ms (typical)

---

## 🗂️ Project Structure

```
pyTweeter/
├── wxAsyncNewsGatherAPI.py       # 🚀 Main service (FastAPI + Collector)
├── wxAsyncNewsGather.py          # 📡 News collector module
├── wxAsyncNewsReaderv6.py        # 🖥️  GUI application
├── article_fetcher.py            # 📄 Content fetcher
├── async_tickdb.py               # ⏰ Scheduling system
├── predator_news.db              # 💾 SQLite database
├── .env                          # 🔐 Configuration
├── requirements-fastapi.txt      # 📦 FastAPI dependencies
├── requirements.txt              # 📦 All dependencies
├── wxAsyncNewsGatherAPI.service  # ⚙️  Systemd service file
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

**jamaj**

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

## 📝 Recent Changes

### March 2026
- ✅ Migrated to FastAPI from Flask
- ✅ Unified collector and API in single process
- ✅ Added systemd service (wxAsyncNewsGatherAPI)
- ✅ Improved timezone detection (96.5% coverage)
- ✅ Added `inserted_at_ms` timestamp for efficient queries
- ✅ Migrated from PostgreSQL to SQLite
- ✅ Updated GUI to wxAsyncNewsReaderv6
- ✅ Added API polling with real-time updates

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

**Last Updated**: March 17, 2026
