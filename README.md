# pyTweeter - Real-Time News & Social Media Aggregator

## ⚠️ PROJECT STATUS: REQUIRES MODERNIZATION

**Last Updated:** 2026-02-26

### Current State
- ❌ **Twitter Integration:** BROKEN (API deprecated)
- ⚠️ **News Collection:** LIMITED (free tier restrictions)
- ✅ **GUI:** Functional
- ❌ **Security:** Critical issues (exposed credentials)

---

## Overview

This project was designed to collect tweets and RSS news, hash them for deduplication, store in Redis and PostgreSQL databases, and display real-time news updates through a wxPython GUI.

### Features
- Async news collection from NewsAPI.org
- PostgreSQL storage with SQLAlchemy
- Redis caching for social media posts
- wxPython desktop GUI
- Multi-language support (English, Portuguese, Spanish, Italian)

---

## ⚠️ CRITICAL: Read Before Using

1. **Twitter API is NON-FUNCTIONAL**
   - Twitter deprecated the v1.1 Streaming API
   - X (Twitter) now requires paid subscription ($100+/month)
   - See [ANALYSIS_AND_REFACTORING_PLAN.md](ANALYSIS_AND_REFACTORING_PLAN.md) for migration options

2. **Exposed Credentials**
   - API keys and passwords are currently hardcoded
   - **DO NOT commit .env files to version control**
   - Follow Phase 1 security fixes immediately

3. **Dependencies May Be Outdated**
   - Some libraries are unmaintained (Peony)
   - Python 3.7-3.8 era code
   - Requires testing in modern environments

---

## Quick Start (News-Only Mode)

### Prerequisites
- Python 3.10+
- PostgreSQL 12+
- Redis 5+

### Installation

1. **Clone repository** (if not already)
```bash
cd /home/jamaj/src/python/pyTweeter
```

2. **Create virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate  # On Linux/Mac
# venv\Scripts\activate  # On Windows
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment variables**
```bash
cp .env.example .env
nano .env  # Edit with your credentials
```

5. **Set up PostgreSQL database**
```bash
createdb predator3_dev
# Or use your preferred database name
```

6. **Run news collector**
```bash
python wxAsyncNewsGather.py
```

7. **Run GUI news reader**
```bash
python wxAsyncNewsReaderv5.py
```

---

## Architecture

```
┌─────────────────┐
│   NewsAPI.org   │
│  (4 languages)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ wxAsyncNewsGather│
│  (Collector)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌─────────────┐
│   PostgreSQL    │◄─────┤ Redis Cache │
│  gm_sources     │      │             │
│  gm_articles    │      └─────────────┘
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│wxAsyncNewsReader│
│   (GUI Viewer)  │
└─────────────────┘
```

---

## File Structure

### Active Files
- `wxAsyncNewsGather.py` - News collection worker
- `wxAsyncNewsReaderv5.py` - GUI application
- `redis_twitter.py` - Redis helper functions
- `predator_gm.py` - Database utilities

### Deprecated Files (DO NOT USE)
- `twitterasync_new.py` - Broken Twitter collector
- `twitterasync.py` - Old Twitter collector
- `wxAsyncNewsReaderv1-4.py` - Old GUI versions

### Configuration
- `.env` - Environment variables (create from `.env.example`)
- `requirements.txt` - Python dependencies

---

## Configuration

### Database Configuration
Edit `.env`:
```bash
DB_HOST=localhost
DB_PORT=5432
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=predator3_dev
```

### NewsAPI Configuration
Get free API key at https://newsapi.org/register

```bash
NEWS_API_KEYS=key1,key2,key3,key4
LANGUAGES=en,pt,es,it
UPDATE_INTERVAL_SEC=600
```

### Redis Configuration
```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

---

## Known Issues

1. **Twitter API Broken**
   - Solution: Remove Twitter code or migrate to alternatives

2. **NewsAPI Rate Limits**
   - Free tier: 100 requests/day per key
   - Currently using 4 keys = 400 requests/day
   - Updates every 10 minutes = ~144 requests/day per language
   - Will hit limits with 4 languages simultaneously
   - Solution: Implement caching and stagger requests

3. **Hardcoded Credentials**
   - Credentials currently in source files
   - Solution: Move to .env (Phase 1 of refactoring plan)

4. **No Error Handling**
   - Minimal exception handling
   - Solution: Add try/except blocks and logging

5. **Multiple File Versions**
   - 5+ versions of some modules
   - Solution: Consolidate to single version

---

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
