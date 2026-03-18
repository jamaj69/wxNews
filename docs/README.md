# wxNews - Real-Time News Aggregator

## ✅ PROJECT STATUS: PRODUCTION READY

**Last Updated:** March 17, 2026

### Current State
- ✅ **FastAPI Backend:** Fully functional with REST API
- ✅ **News Collection:** NewsAPI + RSS + MediaStack (480+ sources)
- ✅ **GUI:** Modern wxPython interface with real-time polling
- ✅ **Database:** SQLite with efficient indexing
- ✅ **Security:** Environment-based configuration (.env)
- ✅ **Timezone:** 96.5% automatic coverage
- ✅ **Service:** Systemd integration with auto-restart

---

## Overview

**wxNews** is a modern news aggregation system designed to collect, store, and display news from multiple sources through a unified interface.

### Features
- ✅ Async news collection from NewsAPI, RSS feeds, and MediaStack
- ✅ FastAPI REST API with automatic Swagger documentation
- ✅ SQLite storage with SQLAlchemy ORM
- ✅ wxPython desktop GUI with real-time updates
- ✅ Multi-language support (English, Portuguese, Spanish, Italian)
- ✅ Automatic timezone detection and normalization
- ✅ Content enrichment with full article fetching
- ✅ Deduplication by URL
- ✅ Systemd service integration

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│            wxAsyncNewsGatherAPI.py (systemd)                 │
│                                                               │
│  ┌──────────────────────┐   ┌──────────────────────────┐   │
│  │  FastAPI Server      │   │  News Collectors         │   │
│  │  (Port 8765)         │   │  (Parallel Async Tasks)  │   │
│  ├──────────────────────┤   ├──────────────────────────┤   │
│  │ • /api/articles      │   │ • NewsAPI (4 keys)       │   │
│  │ • /api/sources       │   │ • RSS Feeds (480+ src)   │   │
│  │ • /api/stats         │   │ • MediaStack (7500+ src) │   │
│  │ • /api/health        │   │                          │   │
│  │ • /docs (Swagger)    │   │ Continuous collection    │   │
│  └──────────────────────┘   └──────────────────────────┘   │
│             │                          │                     │
│             └─────────┬────────────────┘                     │
│                       ▼                                      │
│            ┌─────────────────────┐                          │
│            │  predator_news.db   │                          │
│            │  (SQLite)           │                          │
│            │  • gm_articles      │                          │
│            │  • gm_sources       │                          │
│            │  • gm_newsapi_src   │                          │
│            └─────────────────────┘                          │
└──────────────────────────────────────────────────────────────┘
                       ▲
                       │ HTTP API (polling every 30s)
                       │
            ┌──────────────────────┐
            │ wxAsyncNewsReaderv6  │
            │  (wxPython GUI)      │
            │                      │
            │ • Source filtering   │
            │ • Real-time updates  │
            │ • HTML rendering     │
            │ • 480+ sources       │
            └──────────────────────┘
```

---

## Quick Start

### Prerequisites
- Python 3.10+
- SQLite 3
- wxPython 4.2+

### Installation

1. **Install Dependencies**
```bash
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate
pip install -r requirements-fastapi.txt
```

2. **Configure Environment**
```bash
# Edit .env file with your API keys
nano .env
```

3. **Start Backend Service**
```bash
sudo systemctl start wxAsyncNewsGatherAPI.service
sudo systemctl status wxAsyncNewsGatherAPI.service
```

4. **Start GUI**
```bash
python wxAsyncNewsReaderv6.py
```

---

## Configuration

### Environment Variables (.env)

```bash
# NewsAPI Keys (https://newsapi.org)
NEWS_API_KEY_1=your_primary_key
NEWS_API_KEY_2=your_secondary_key

# MediaStack (optional, https://mediastack.com)
MEDIASTACK_API_KEY=your_mediastack_key

# Database
DB_PATH=predator_news.db

# API Configuration  
NEWS_API_URL=http://localhost:8765
NEWS_API_PORT=8765
NEWS_API_HOST=0.0.0.0

# Polling Interval (GUI)
NEWS_POLL_INTERVAL_MS=30000  # 30 seconds

# Collection Intervals (seconds)
NEWSAPI_UPDATE_INTERVAL=600      # 10 minutes
RSS_UPDATE_INTERVAL=1800         # 30 minutes
MEDIASTACK_UPDATE_INTERVAL=3600  # 1 hour
```

---

## Components

### 1. Backend Service (wxAsyncNewsGatherAPI.py)

**Purpose**: Unified FastAPI application running news collection and REST API

**Features**:
- FastAPI server with automatic OpenAPI documentation
- Three parallel collectors (NewsAPI, RSS, MediaStack)
- Timestamp-based article queries
- Source filtering
- Health checks and statistics
- CORS middleware for web clients

**Systemd Service**: `/etc/systemd/system/wxAsyncNewsGatherAPI.service`

**Management**:
```bash
sudo systemctl start wxAsyncNewsGatherAPI.service
sudo systemctl stop wxAsyncNewsGatherAPI.service
sudo systemctl restart wxAsyncNewsGatherAPI.service
journalctl -u wxAsyncNewsGatherAPI.service -f
```

**API Endpoints**:
- `GET /` - API information
- `GET /docs` - Interactive Swagger UI
- `GET /api/health` - Health check
- `GET /api/articles?since=<ms>&limit=<n>` - Query articles
- `GET /api/latest_timestamp` - Latest insertion timestamp
- `GET /api/sources` - List available sources
- `GET /api/stats` - Collection statistics

---

### 2. GUI Client (wxAsyncNewsReaderv6.py)

**Purpose**: Desktop interface for browsing collected news

**Features**:
- wx.Notebook tabbed interface
- CheckListBox for source selection (480+ sources)
- Real-time API polling (configurable interval)
- HTML article rendering with wx.html2
- Article detail viewer
- Auto-refresh on source changes
- Select All / Deselect All / Load Checked buttons
- Future timestamp filtering (data integrity)

**Startup**:
```bash
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate
python wxAsyncNewsReaderv6.py
```

---

### 3. Database (predator_news.db)

**Engine**: SQLite 3

**Tables**:
- `gm_articles` - News articles (~55k+)
  - `id_article` - Primary key
  - `title`, `description`, `url`, `author`
  - `published_at` - Original timestamp string
  - `published_at_gmt` - Normalized Unix timestamp
  - `inserted_at_ms` - Millisecond insertion timestamp
  - `content` - Full article content
  - `source_name`, `id_source` - Source identifiers
  - `use_timezone` - Timezone detection flag

- `gm_sources` - Source catalog (480+ entries)
  - `id_source` - Primary key
  - `source_name` - Display name
  - `url` - RSS feed URL or API source
  - `timezone` - Configured timezone
  - `use_timezone` - Enable automatic timezone detection

- `gm_newsapi_sources` - NewsAPI source registry

**Indexes**:
- `idx_articles_inserted_at_ms` - Fast timestamp queries
- `idx_articles_url` - Deduplication
- `idx_articles_source` - Source filtering

---

## API Usage Examples

### Health Check
```bash
curl http://localhost:8765/api/health
```

### Get Recent Articles
```bash
# Get 50 articles since timestamp
curl "http://localhost:8765/api/articles?since=1710000000000&limit=50"

# Filter by sources
curl "http://localhost:8765/api/articles?since=1710000000000&sources=bbc,cnn&limit=20"
```

### Get Statistics
```bash
curl http://localhost:8765/api/stats | python -m json.tool
```

### Interactive Documentation
Open browser: `http://localhost:8765/docs`

---

## Database Queries

```bash
# Total articles
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles;"

# Recent articles
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
```

---

## Migration History

### March 2026
- ✅ Migrated to FastAPI from Flask
- ✅ Unified collector and API in single process
- ✅ Added systemd service integration
- ✅ Improved timezone detection (96.5% coverage)
- ✅ Added timestamp-based queries
- ✅ Migrated from PostgreSQL to SQLite
- ✅ Updated GUI to wxAsyncNewsReaderv6
- ✅ Added API polling with real-time updates

---

## File Structure

### Active Components
- `wxAsyncNewsGatherAPI.py` - Main service (FastAPI + Collector)
- `wxAsyncNewsGather.py` - News collection module
- `wxAsyncNewsReaderv6.py` - GUI application (current version)
- `article_fetcher.py` - Content fetcher
- `async_tickdb.py` - Async scheduler
- `predator_news.db` - SQLite database

### Configuration Files
- `.env` - Environment variables (API keys, config)
- `requirements-fastapi.txt` - FastAPI dependencies
- `requirements.txt` - All dependencies
- `wxAsyncNewsGatherAPI.service` - Systemd service file

### Documentation
- `README.md` - Main project README (root)
- `copilot-instructions.md` - Operations guide
- `QUICK_REFERENCE.md` - Command reference
- `FASTAPI_DOCUMENTATION.md` - API documentation
- `FASTAPI_README.md` - FastAPI migration summary
- `docs/` - Technical documentation (30+ files)

### Deprecated Files (Archived)
- `wxAsyncNewsReaderv[1-5].py` - Old GUI versions
- `twitterasync*.py` - Twitter integration (API deprecated)
- Database recovery scripts - PostgreSQL era
- `wxAsyncNewsGather.service` - Old service file (replaced by API version)

---

## Troubleshooting

### Service Not Starting

```bash
# Check logs
journalctl -u wxAsyncNewsGatherAPI.service -n 100

# Check if port is in use
sudo lsof -i :8765

# Verify environment
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

# Check configuration
grep NEWS_API_URL .env

# Test API endpoint
curl http://localhost:8765/api/articles?since=0&limit=10
```

### No New Articles Collected

```bash
# Check collector logs
journalctl -u wxAsyncNewsGatherAPI.service -f | grep "Collected"

# Verify API keys
python -c "from decouple import config; print('Key exists:', bool(config('NEWS_API_KEY_1')))"

# Check last collection
sqlite3 predator_news.db "
SELECT datetime(MAX(inserted_at_ms)/1000, 'unixepoch') as last_insert 
FROM gm_articles;"

# Test NewsAPI directly
curl "https://newsapi.org/v2/top-headlines?country=us&apiKey=YOUR_KEY"
```

### Database Issues

```bash
# Check integrity
sqlite3 predator_news.db "PRAGMA integrity_check;"

# Check schema
sqlite3 predator_news.db ".schema gm_articles"

# Rebuild indexes
sqlite3 predator_news.db "REINDEX;"

# Database size
ls -lh predator_news.db
```

---

## Monitoring & Maintenance

### Daily Checks

```bash
# Service status
sudo systemctl status wxAsyncNewsGatherAPI.service

# Recent articles
sqlite3 predator_news.db "
SELECT COUNT(*) FROM gm_articles 
WHERE published_at_gmt > unixepoch('now', '-1 day');"

# API health
curl http://localhost:8765/api/health
```

### Weekly Maintenance

```bash
# Backup database
cp predator_news.db backups/predator_news_$(date +%Y%m%d).db

# Check timezone coverage
python check_gmt_coverage.py

# View statistics
curl http://localhost:8765/api/stats | python -m json.tool
```

### Cleanup (Monthly)

```bash
# Remove articles older than 90 days
sqlite3 predator_news.db "
DELETE FROM gm_articles 
WHERE published_at_gmt < unixepoch('now', '-90 days');"

# Remove duplicates
bash run_cleanup.sh

# Vacuum database
sqlite3 predator_news.db "VACUUM;"
```

---

## Documentation Index

### Getting Started
- [Main README](../README.md) - Project overview
- [NEWS_QUICK_START.md](NEWS_QUICK_START.md) - Beginner's guide
- [QUICK_REFERENCE.md](../QUICK_REFERENCE.md) - Command reference

### Technical Documentation
- [FASTAPI_DOCUMENTATION.md](../FASTAPI_DOCUMENTATION.md) - API architecture
- [FASTAPI_README.md](../FASTAPI_README.md) - FastAPI migration
- [USE_TIMEZONE_SYSTEM.md](USE_TIMEZONE_SYSTEM.md) - Timezone system
- [SQLITE_MIGRATION.md](SQLITE_MIGRATION.md) - Database migration
- [CONTENT_ENRICHMENT.md](CONTENT_ENRICHMENT.md) - Content fetching

### Operations
- [copilot-instructions.md](../copilot-instructions.md) - System operations
- [POLLING_TESTING_GUIDE.md](../POLLING_TESTING_GUIDE.md) - API testing

### Analysis & Reports
- [TIMEZONE_AUTO_DETECTION.md](TIMEZONE_AUTO_DETECTION.md) - Timezone coverage
- [RSS_VALIDATION_REPORT.md](RSS_VALIDATION_REPORT.md) - Feed validation
- [DATABASE_OPTIMIZATION.md](DATABASE_OPTIMIZATION.md) - Optimization guide
- [LOST_SOURCES_ANALYSIS.md](LOST_SOURCES_ANALYSIS.md) - Source analysis

---

## Contributing

### Development Setup

```bash
# Clone repository
git clone https://github.com/jamaj69/wxNews.git
cd wxNews

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install development dependencies
pip install -r requirements-fastapi.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Run tests
python test_fastapi_news.py
python test_api_polling.py
```

### Code Style

- Python 3.10+ features
- Type hints where appropriate
- Async/await for I/O operations
- SQLAlchemy for database access
- FastAPI best practices

### Testing

```bash
# Test API endpoints
python test_fastapi_news.py

# Test database
python test_db_sanitize.py

# Test content parsing
python test_html_parser.py
```

---

## Performance

### Current Metrics
- **Articles**: 55,000+
- **Sources**: 480+
- **API Response Time**: <100ms (typical)
- **Database Size**: ~150MB
- **Memory Usage**: ~200MB (service)
- **CPU Usage**: <10% (idle), ~30% (collecting)

### Optimization Tips
1. **Database**: Regular vacuuming and indexing
2. **Collection**: Stagger update intervals by source type
3. **API**: Use timestamp queries for efficient polling
4. **GUI**: Limit sources loaded simultaneously

---

## License

MIT License - See LICENSE file for details

---

## Support

For issues, questions, or contributions:
- GitHub: [@jamaj69/wxNews](https://github.com/jamaj69/wxNews)
- Documentation: [docs/README.md](README.md)

---

**Last Updated**: March 17, 2026


## Refactoring Plan

See **[ANALYSIS_AND_REFACTORING_PLAN.md](ANALYSIS_AND_REFACTORING_PLAN.md)** for:
- Complete code analysis
- Security recommendations
- Architecture redesign
- Migration strategies
- 7-week refactoring timeline
- Technology alternatives

### Priority Actions
1. 🔴 **Phase 1 (Week 1):** Security fixes - move credentials to .env
2. 🟠 **Phase 2 (Week 2-3):** Architecture refactoring - package structure
3. 🟠 **Phase 3 (Week 4):** Replace Twitter with Mastodon/RSS
4. 🟡 **Phase 4 (Week 5):** Testing and CI/CD
5. 🟢 **Phase 5 (Week 6+):** Feature enhancements

---

## Testing

Currently **no automated tests exist**. Manual testing only.

### To Test News Collection
```bash
python wxAsyncNewsGather.py
# Watch console for API responses
# Check PostgreSQL for new records
```

### To Test GUI
```bash
python wxAsyncNewsReaderv5.py
# Check if sources populate (left panel)
# Click source to see articles (right panel)
# Click article to open in browser
```

---

## Dependencies

### Core
- Python 3.10+
- asyncio, aiohttp
- wxPython, wxasync
- Redis, PostgreSQL

### Full List
See `requirements.txt` (to be created during Phase 1)

---

## Contributing

Project is in maintenance/refactoring mode. Before contributing:

1. Read [ANALYSIS_AND_REFACTORING_PLAN.md](ANALYSIS_AND_REFACTORING_PLAN.md)
2. Check if Twitter replacement is implemented
3. Ensure credentials are in .env (not source code)
4. Follow new package structure (Phase 2)

---

## License

*License information not currently specified*

---

## Support

For questions or issues regarding:
- **Architecture:** See ANALYSIS_AND_REFACTORING_PLAN.md
- **Twitter Migration:** See "Phase 3: Twitter Replacement"
- **Security:** See "Phase 1: Emergency Fixes"

---

## Changelog

### 2026-02-26 - Analysis & Documentation
- Created comprehensive analysis document
- Documented all programs and architecture
- Identified critical security issues
- Created 7-week refactoring plan
- Confirmed Twitter API is non-functional

### 2019-2020 - Original Development
- Initial Twitter streaming implementation
- NewsAPI integration
- Redis and PostgreSQL storage
- wxPython GUI

---

## Credits

**Original Author:** jamaj  
**Created:** 2019  
**Analysis Date:** 2026-02-26

---

## Next Steps

1. **Immediate:**
   ```bash
   # Create .env file
   cp .env.example .env
   nano .env
   
   # Test news collection
   python wxAsyncNewsGather.py
   ```

2. **This Week:**
   - Remove Twitter code
   - Extract credentials to .env
   - Create requirements.txt
   - Test on clean Python environment

3. **This Month:**
   - Implement RSS feed support
   - Add Mastodon integration
   - Refactor package structure
   - Add basic tests

---

**For detailed technical analysis and refactoring roadmap, see:**  
📋 **[ANALYSIS_AND_REFACTORING_PLAN.md](ANALYSIS_AND_REFACTORING_PLAN.md)**
