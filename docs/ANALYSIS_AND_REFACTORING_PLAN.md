# pyTweeter - Analysis and Refactoring Plan

## Executive Summary

This project collects tweets and RSS news, hashes them, stores in databases (Redis and PostgreSQL), and displays real-time news updates through a wxPython GUI.

**Created:** 2026-02-26  
**Status:** Legacy code requiring modernization

---

## 1. TWITTER CREDENTIALS ANALYSIS

### ⚠️ CRITICAL ISSUE: Twitter API Access

**Current Status:** The Twitter credentials are **OUTDATED and LIKELY NON-FUNCTIONAL**

#### Twitter API Credentials Found:
- **Location:** [twitterasync_new.py](twitterasync_new.py#L166-L169) and [twitterasync.py](twitterasync.py#L166-L169)
- **API Version:** Old Twitter API v1.1 (using OAuth 1.0a)
- **Library:** `Peony` (async Twitter client)

```python
CONSUMER_KEY = 'j1KOc2AWQ5QvrtNe8N15UfcXI'
CONSUMER_SECRET = 'AjHnwNBhBB1eegMcVYDvVBiQMAX6PHX9OOdqbqFSHHeezB9IJF'
ACCESS_TOKEN = '1201408473151496192-KZ2xMa2GSuanbi8UJtyFaH4XQ5foWa'
ACCESS_TOKEN_SECRET = 'rUgHWt9z252O0tX94GjO0Zs518NIWiCCXm1slluLX86T0'
```

#### Problems:
1. **Exposed Credentials:** API keys are hardcoded in source files (security risk)
2. **Twitter API Changes:** Twitter deprecated free API access (2023) and deprecated v1.1 endpoints
3. **X (Twitter) Migration:** Platform renamed to X with new API pricing tiers
4. **Old API Endpoints:** Uses `statuses.filter` stream endpoint (likely disabled)

#### Recommendation:
- **Cannot verify without testing** - These keys may be revoked or restricted
- **Migration Required:** Need to upgrade to Twitter API v2 or X API
- **Cost:** X API now requires paid subscription (Basic $100/month minimum)
- **Alternative:** Consider switching to Mastodon, Bluesky, or RSS-only feeds

---

## 2. NEWS API CREDENTIALS

### Status: ✅ **Likely Still Working (but limited)**

**Location:** Multiple files (wxAsyncNewsGather.py, wxAsyncNewsReaderv5.py, etc.)

```python
API_KEY1 = 'c85890894ddd4939a27c19a3eff25ece'  # predator@jamaj.com.br
API_KEY2 = '4327173775a746e9b4f2632af3933a86'  # jamaj@jamaj.com.br
API_KEY3 = 'c85890894ddd4939a27c19a3eff25ece'  # (duplicate)
API_KEY4 = '4327173775a746e9b4f2632af3933a86'  # (duplicate)
```

**API Provider:** NewsAPI.org  
**Limitations:**
- Free tier: 100 requests/day, 30-day article history
- Delays on breaking news (15 minutes)
- Only top headlines in free tier

---

## 3. DATABASE CREDENTIALS

### ⚠️ SECURITY CRITICAL: Exposed Database Credentials

**PostgreSQL Database:**
```python
def dbCredentials():
    return {
        'user': 'predator',
        'password': 'fuckyou',  # ⚠️ PLAINTEXT PASSWORD
        'host': 'titan',
        'dbname': 'predator3_dev'
    }
```

**Redis Database:**
```python
conn = redis.Redis(host='localhost', port=6379, db=0)
```

#### Issues:
- Plaintext passwords in source code
- No environment variable configuration
- Database names suggest development environment in production use
- Host 'titan' suggests hardcoded hostname (not portable)

---

## 4. PROGRAM ARCHITECTURE

### 4.1 Core Modules

#### A) **Twitter Collection Module**

**Files:**
- [twitterasync_new.py](twitterasync_new.py) - Main async Twitter stream processor (339 lines)
- [twitterasync.py](twitterasync.py) - Older version (277 lines)
- [redis_twitter.py](redis_twitter.py) - Redis helper functions (124 lines)

**Functionality:**
- Connects to Twitter Streaming API
- Filters tweets from specific user IDs (16 monitored users)
- Excludes retweets and replies
- Stores in Redis using hash-based deduplication
- Uses `Peony` async library with asyncio

**Data Flow:**
```
Twitter Stream → process_tweet() → create_user() → create_status() → Redis
                                     ↓
                              (filters retweets/replies)
```

**Redis Schema:**
- `users:` - Hash mapping lowercase username to user ID
- `user:{id}` - Hash with user details (login, followers, posts, etc.)
- `status:{id}` - Hash with tweet content and metadata
- Distributed locking for user creation

#### B) **News Collection Module**

**Files:**
- [wxAsyncNewsGather.py](wxAsyncNewsGather.py) - Async news fetcher (378 lines)
- [wxAsyncNewsGather1.py](wxAsyncNewsGather1.py) - Variant version

**Functionality:**
- Fetches top headlines from NewsAPI.org
- Supports 4 languages: English, Portuguese, Spanish, Italian
- Updates every 10 minutes (600 seconds)
- Stores in PostgreSQL database
- URL-based hashing for deduplication

**Data Flow:**
```
NewsAPI.org → async_getALLNews() → PostgreSQL
                   ↓
           (4 API calls, one per language)
                   ↓
           Article hash = base64(zlib(title+url+date))[15:31]
```

**Database Schema:**
```sql
gm_sources (
    id_source PRIMARY KEY,
    name, description, url,
    category, language, country
)

gm_articles (
    id_article PRIMARY KEY,  -- hashed URL
    id_source FOREIGN KEY,
    author, title, description,
    url, urlToImage, publishedAt, content
)
```

#### C) **GUI News Reader Module**

**Files:**
- [wxAsyncNewsReaderv5.py](wxAsyncNewsReaderv5.py) - Latest GUI version (315 lines)
- [wxAsyncNewsReaderv4.py](wxAsyncNewsReaderv4.py) - Previous version
- [wxAsyncNewsReaderv3.py](wxAsyncNewsReaderv3.py) - Older version
- [wxAsyncNewsReader.py](wxAsyncNewsReader.py) - Original version
- [wxnewsviewer.py](wxnewsviewer.py) - Legacy synchronous viewer

**Functionality:**
- wxPython GUI with two-panel layout
- Left panel: News sources list
- Right panel: Article titles with timestamps
- Clicking opens article in web browser
- Auto-refresh every 60 seconds
- Uses `wxasync` for async operations

**GUI Structure:**
```
MainWindow (wx.Frame)
    └── NewsPanel (wx.Panel)
            ├── sources_list (wx.ListCtrl)
            └── news_list (wx.ListCtrl)
                    └── columns: [Link, Title, Hash, Timestamp]
```

---

### 4.2 Supporting Modules

**Database Management:**
- [predator_gm.py](predator_gm.py) - PostgreSQL utilities and table creation
- [dbtest1.py](dbtest1.py) - Database connection testing

**COVID-19 Data (Unrelated):**
- [covid.py](covid.py), [covid19_import.py](covid19_import.py) - COVID data importers
- Various `.tsv` and `.csv` COVID data files

**Other:**
- [geo_demo.ipynb](geo_demo.ipynb), [geo_demo1.py](geo_demo1.py) - Geo visualization experiments
- [translate.py](translate.py) - Translation utilities
- [images.py](images.py) - Image handling

---

### 4.3 Technology Stack

| Component | Technology | Version Issue |
|-----------|-----------|---------------|
| **Python** | Python 3.x | Likely 3.7-3.8 based on code patterns |
| **Async I/O** | asyncio + aiohttp | ✅ Modern |
| **Twitter API** | Peony (async client) | ⚠️ Unmaintained since 2020 |
| **Twitter API Version** | v1.1 Streaming | ❌ Deprecated |
| **GUI Framework** | wxPython 4.x + wxasync | ✅ Still viable |
| **News API** | NewsAPI.org REST | ✅ Active |
| **Twitter Storage** | Redis | ✅ Modern |
| **News Storage** | PostgreSQL + SQLAlchemy | ✅ Modern |
| **Hash Algorithm** | base64(zlib(data)) | ⚠️ Non-crypto hash |

---

## 5. CODE QUALITY ISSUES

### 5.1 Security Vulnerabilities

1. **Hardcoded Credentials** (CRITICAL)
   - All API keys and passwords in source code
   - Version control exposes secrets
   - No `.env` or config file usage

2. **SQL Injection Risk** (MEDIUM)
   - Some SQL queries use string formatting
   - Most queries use SQLAlchemy (safer)

3. **No Input Validation** (LOW)
   - Tweet data processed without sanitization
   - Assumes API responses are well-formed

### 5.2 Code Duplication

1. **Multiple News Reader Versions**
   - 5 versions of wxAsyncNewsReader (v1-v5)
   - 2 versions of wxAsyncNewsGather
   - No clear "main" version

2. **Duplicate Twitter Scripts**
   - `twitterasync.py` vs `twitterasync_new.py`
   - Nearly identical code (277 vs 339 lines)
   - Only difference: logging and error handling

3. **Repeated Helper Functions**
   - `ToString()`, `ConvDictValuesToString()` duplicated
   - `acquire_lock_with_timeout()` copied across files
   - `dbCredentials()` repeated 5+ times

### 5.3 Poor Code Organization

1. **No Package Structure**
   - All files in root directory
   - No modules or packages
   - No `__init__.py` files

2. **Mixed Concerns**
   - COVID-19 code mixed with Twitter/news code
   - Unrelated geo visualization files
   - Test files (`dbtest1.py`) in main directory

3. **Inconsistent Naming**
   - Mix of camelCase and snake_case
   - Some classes use PascalCase, others don't
   - Variable names: `llogin`, `lRetweet`, `lTrue`

### 5.4 Technical Debt

1. **Commented-Out Code**
   - Extensive commented blocks
   - Old API keys kept as comments
   - Debug print statements everywhere

2. **No Error Handling**
   - Minimal try/except blocks
   - No graceful degradation
   - No logging strategy (except in twitterasync_new.py)

3. **No Tests**
   - Zero unit tests
   - Zero integration tests
   - Manual testing only

4. **No Documentation**
   - No README.md
   - No docstrings (except auto-generated)
   - No API documentation

---

## 6. FUNCTIONAL ISSUES

### 6.1 Twitter Stream

**Status:** ❌ **BROKEN** (API deprecated)

**Problems:**
- Twitter v1.1 Streaming API shutdown
- Free tier no longer available
- `statuses.filter` endpoint removed
- Peony library unmaintained since 2020

**Impact:** Core functionality completely non-functional

### 6.2 News Collection

**Status:** ⚠️ **LIMITED** (free tier restrictions)

**Problems:**
- 100 requests/day limit (25 per API key × 4 keys)
- Fetching 4 languages × 100 articles = 400 items every 10 min
- Will hit rate limit quickly
- 15-minute delay on breaking news

**Impact:** Functional but severely rate-limited

### 6.3 Database Storage

**Status:** ✅ **FUNCTIONAL** (if databases running)

**Assumptions:**
- PostgreSQL server running on host 'titan'
- Redis server running on localhost
- Network connectivity to 'titan'
- Database 'predator3_dev' exists

---

## 7. REFACTORING PLAN

### Phase 1: Emergency Fixes (Week 1)

#### 1.1 Security
- [ ] Move all credentials to `.env` file
- [ ] Install `python-decouple` or `python-dotenv`
- [ ] Add `.env` to `.gitignore`
- [ ] Create `.env.example` template
- [ ] Audit git history for exposed secrets

#### 1.2 Code Cleanup
- [ ] Remove commented-out code
- [ ] Delete unused files (old versions)
- [ ] Choose one version of each module
- [ ] Remove COVID-19 unrelated files (or move to separate project)

#### 1.3 Documentation
- [ ] Create `README.md` with setup instructions
- [ ] Document current state (broken Twitter API)
- [ ] List dependencies in `requirements.txt`
- [ ] Document database schema

---

### Phase 2: Architecture Refactoring (Week 2-3)

#### 2.1 Package Structure
```
pyTweeter/
├── README.md
├── requirements.txt
├── .env.example
├── .env (gitignored)
├── setup.py
├── pytweeter/
│   ├── __init__.py
│   ├── config.py                 # Centralized config
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py               # Abstract base collector
│   │   ├── news_collector.py    # NewsAPI collector
│   │   └── social_collector.py  # Social media (future)
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── redis_store.py
│   │   └── postgres_store.py
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py
│   │   └── news_panel.py
│   └── utils/
│       ├── __init__.py
│       ├── hash.py
│       └── converters.py
├── tests/
│   ├── __init__.py
│   ├── test_collectors.py
│   └── test_storage.py
└── scripts/
    ├── run_news_collector.py
    └── run_gui.py
```

#### 2.2 Configuration Management
Create `config.py`:
```python
from decouple import config
from dataclasses import dataclass

@dataclass
class DatabaseConfig:
    host: str = config('DB_HOST', default='localhost')
    port: int = config('DB_PORT', default=5432, cast=int)
    user: str = config('DB_USER')
    password: str = config('DB_PASSWORD')
    database: str = config('DB_NAME')

@dataclass
class RedisConfig:
    host: str = config('REDIS_HOST', default='localhost')
    port: int = config('REDIS_PORT', default=6379, cast=int)
    db: int = config('REDIS_DB', default=0, cast=int)

@dataclass
class NewsAPIConfig:
    api_keys: list[str] = config('NEWS_API_KEYS', cast=lambda x: x.split(','))
    languages: list[str] = config('LANGUAGES', default='en,pt,es,it', cast=lambda x: x.split(','))
    update_interval: int = config('UPDATE_INTERVAL_SEC', default=600, cast=int)
```

#### 2.3 Abstract Base Classes
```python
# collectors/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any

class BaseCollector(ABC):
    """Abstract base class for all content collectors"""
    
    @abstractmethod
    async def collect(self) -> AsyncIterator[Dict[str, Any]]:
        """Yield collected items"""
        pass
    
    @abstractmethod
    def validate_config(self) -> bool:
        """Validate collector configuration"""
        pass
```

---

### Phase 3: Twitter Replacement (Week 4)

#### Option A: Migrate to Mastodon
- Open source, decentralized
- Free API access
- Similar streaming capabilities
- Library: `Mastodon.py`

#### Option B: Switch to Reddit
- Free API (restricted)
- Good for news aggregation
- Library: `praw` (async: `asyncpraw`)

#### Option C: RSS-Only Mode
- No API costs
- Reliable, universal
- Library: `feedparser` + `aiohttp`
- Add major news sources

#### Option D: Bluesky
- New Twitter alternative
- AT Protocol
- Growing user base
- Library: `atproto`

**Recommendation:** Start with **Option C (RSS-Only)** + **Option A (Mastodon)**

---

### Phase 4: Testing & CI/CD (Week 5)

#### 4.1 Testing Strategy
- [ ] Add `pytest` + `pytest-asyncio`
- [ ] Unit tests for utilities (hash, converters)
- [ ] Integration tests for collectors (mocked APIs)
- [ ] Integration tests for storage (test databases)
- [ ] GUI tests with `pytest-qt` or manual QA

#### 4.2 Continuous Integration
- [ ] GitHub Actions or GitLab CI
- [ ] Run tests on push
- [ ] Code quality checks (flake8, black, mypy)
- [ ] Security scanning (bandit, safety)

#### 4.3 Deployment
- [ ] Docker containerization
- [ ] docker-compose for multi-service setup
- [ ] Environment-based configuration

---

### Phase 5: Feature Enhancements (Week 6+)

#### 5.1 Monitoring & Observability
- [ ] Add structured logging (loguru or structlog)
- [ ] Metrics collection (Prometheus)
- [ ] Error tracking (Sentry)
- [ ] Health check endpoints

#### 5.2 Scalability
- [ ] Connection pooling for databases
- [ ] Rate limiting with backoff
- [ ] Async batch processing
- [ ] Caching layer (Redis)

#### 5.3 User Experience
- [ ] Search functionality in GUI
- [ ] Filters by source/language/date
- [ ] Export to CSV/JSON
- [ ] Dark mode theme
- [ ] Notification system

#### 5.4 Data Quality
- [ ] Content deduplication improvements
- [ ] Sentiment analysis
- [ ] Language detection
- [ ] Article summarization (OpenAI)

---

## 8. MIGRATION CHECKLIST

### Pre-Migration
- [ ] Backup current PostgreSQL database
- [ ] Backup current Redis data
- [ ] Document current data volume
- [ ] Create test environment

### Twitter Deprecation
- [ ] Remove Twitter-specific code
- [ ] Archive old Twitter data
- [ ] Update documentation
- [ ] Notify users (if applicable)

### NewsAPI Enhancement
- [ ] Implement rate limiting
- [ ] Add retry logic with exponential backoff
- [ ] Cache responses
- [ ] Monitor API usage dashboard

### RSS Feed Addition
- [ ] Curate list of RSS sources
- [ ] Implement RSS parser
- [ ] Deduplicate across sources
- [ ] Store RSS metadata

### Mastodon Integration
- [ ] Register Mastodon app
- [ ] Implement OAuth flow
- [ ] Stream timeline/hashtags
- [ ] Store posts in unified format

---

## 9. DEPENDENCIES & REQUIREMENTS

### Current Dependencies (Inferred)
```
peony-twitter>=1.1.0  # ⚠️ Unmaintained
redis>=3.0.0
psycopg2-binary>=2.8.0
SQLAlchemy>=1.3.0
wxPython>=4.1.0
wxasync>=0.4
aiohttp>=3.7.0
requests>=2.25.0
```

### Proposed Dependencies
```
# Core
python>=3.10
asyncio-standard-lib
aiohttp>=3.9.0

# Configuration
python-decouple>=3.8

# Databases
redis>=5.0.0
psycopg2-binary>=2.9.0
SQLAlchemy>=2.0.0
alembic>=1.13.0  # Database migrations

# News & Social
mastodon.py>=1.8.0
feedparser>=6.0.0
atproto>=0.0.40  # Bluesky (optional)

# GUI
wxPython>=4.2.0
wxasync>=0.5

# Utilities
python-dateutil>=2.8.0
pytz>=2023.3

# Development
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
black>=23.0.0
flake8>=6.0.0
mypy>=1.5.0

# Monitoring
loguru>=0.7.0
sentry-sdk>=1.40.0

# Optional
openai>=1.0.0  # For summarization
beautifulsoup4>=4.12.0  # Web scraping
```

---

## 10. ESTIMATED EFFORT

| Phase | Duration | Complexity | Priority |
|-------|----------|------------|----------|
| Phase 1: Emergency Fixes | 1 week | Low | 🔴 Critical |
| Phase 2: Architecture | 2 weeks | Medium | 🟠 High |
| Phase 3: Twitter Replacement | 1 week | Medium | 🟠 High |
| Phase 4: Testing & CI/CD | 1 week | Medium | 🟡 Medium |
| Phase 5: Enhancements | 2+ weeks | High | 🟢 Low |

**Total Refactoring Time:** ~7 weeks (1 developer)

---

## 11. RISKS & MITIGATION

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Twitter API unavailable | High | 100% | ✅ Migrate to alternatives |
| NewsAPI rate limits hit | Medium | 80% | Add caching, multiple keys |
| Database 'titan' unavailable | High | Unknown | Add connection retry, config |
| wxPython compatibility issues | Low | 20% | Test on target platforms |
| Data loss during migration | High | 10% | Backup, staged rollout |
| Cost of paid APIs | Medium | 50% | Use free alternatives first |

---

## 12. SUCCESS METRICS

### Functional
- [ ] News collection running 24/7 without crashes
- [ ] GUI responsive with <100ms article load time
- [ ] Zero exposed credentials in source code
- [ ] 90%+ uptime over 30 days

### Quality
- [ ] 80%+ test coverage
- [ ] Zero critical security vulnerabilities
- [ ] All dependencies up-to-date
- [ ] Type hints on 100% of functions

### Performance
- [ ] <1 second API response time
- [ ] <10MB memory footprint per worker
- [ ] Database queries <50ms average
- [ ] GUI startup time <5 seconds

---

## 13. CONCLUSION

### Current State
- **Twitter Integration:** ❌ Broken (API deprecated)
- **News Collection:** ⚠️ Limited (free tier)
- **GUI:** ✅ Functional (with data)
- **Security:** ❌ Critical issues (exposed credentials)
- **Code Quality:** ⚠️ Technical debt

### Recommended Path Forward

1. **Immediate (Day 1):**
   - Move credentials to environment variables
   - Test NewsAPI functionality
   - Verify database connectivity

2. **Short-term (Week 1-2):**
   - Remove Twitter code (non-functional)
   - Refactor package structure
   - Add basic tests

3. **Medium-term (Week 3-5):**
   - Add RSS feed support
   - Implement Mastodon integration
   - Set up CI/CD pipeline

4. **Long-term (Week 6+):**
   - Add monitoring and logging
   - Implement advanced features
   - Consider web dashboard (FastAPI + React)

### Decision Points

**Should we keep Twitter?**
- **NO** - API access requires $100+/month subscription
- **Alternative:** Mastodon (free) + RSS feeds (free)

**Should we keep wxPython GUI?**
- **YES** - Functional and cross-platform
- **Consider:** Add web dashboard for remote access

**Should we keep PostgreSQL?**
- **YES** - Good choice for structured data
- **Add:** Alembic for schema migrations

**Should we keep Redis?**
- **YES** - Excellent for real-time data and caching
- **Expand:** Use for rate limiting and job queues

---

## APPENDIX A: File Inventory

### Active Files (Keep & Refactor)
- `twitterasync_new.py` - Main Twitter collector (to be replaced)
- `redis_twitter.py` - Redis utilities (refactor into storage module)
- `wxAsyncNewsGather.py` - News collector (refactor)
- `wxAsyncNewsReaderv5.py` - GUI (refactor)
- `predator_gm.py` - Database utilities (refactor)

### Duplicate Files (Delete after consolidation)
- `twitterasync.py` - Old version
- `wxAsyncNewsGather1.py` - Duplicate
- `wxAsyncNewsReaderv2.py`, v3, v4 - Old versions
- `wxAsyncNewsReader.py` - Original version
- `wxnewsviewer.py` - Old synchronous version

### Unrelated Files (Move or Delete)
- All COVID-19 files (`covid*.py`, `*.tsv`, `*.csv`)
- Geo visualization (`geo_*.py`, `geo_demo.ipynb`)
- Test/demo files (`dbtest1.py`, `images.py`, `translate.py`)
- Build artifacts (`hello-rust/`, `dask-worker-space/`)

### Configuration Files (Create)
- `.env` - Environment variables
- `.env.example` - Template
- `requirements.txt` - Dependencies
- `setup.py` or `pyproject.toml` - Package config
- `.gitignore` - Ignore secrets and cache

---

## APPENDIX B: Sample .env Template

```bash
# .env.example - Copy to .env and fill in values

# PostgreSQL Database
DB_HOST=localhost
DB_PORT=5432
DB_USER=predator
DB_PASSWORD=your_password_here
DB_NAME=predator3_dev

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# NewsAPI (newsapi.org)
# Get free API key at: https://newsapi.org/register
NEWS_API_KEYS=key1,key2,key3,key4
LANGUAGES=en,pt,es,it
UPDATE_INTERVAL_SEC=600

# Mastodon (optional)
MASTODON_INSTANCE=https://mastodon.social
MASTODON_ACCESS_TOKEN=your_token_here

# Logging
LOG_LEVEL=INFO
LOG_FILE=pytweeter.log

# GUI
GUI_REFRESH_INTERVAL_MS=60000
GUI_THEME=light

# Monitoring (optional)
SENTRY_DSN=
PROMETHEUS_PORT=9090
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-26  
**Author:** AI Analysis  
**Status:** Draft for Review
