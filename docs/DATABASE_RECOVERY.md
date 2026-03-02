# Database Recovery Plan

## Lost Database: predator3_dev

**Status**: Database not found on any PostgreSQL cluster (ports 5432, 5433, 5435)  
**Recovery Date**: 2026-02-26  
**Recovery Method**: Reconstructed from code and live API sources

---

## Summary of Lost Sources

### Total Sources Recovered: **275+**

| Source Type | Count | Status |
|------------|-------|--------|
| **RSS Feeds** | 157 | ✅ Recovered from `rssfeeds.conf` |
| **NewsAPI Sources** | 118 | ✅ Recovered from live API |
| **Total** | **275** | Ready for database initialization |

---

## 1. RSS Feeds (157 sources)

**File**: `rssfeeds.conf` (JSON configuration)

### Distribution by Category:

| Category | Count | Examples |
|----------|-------|----------|
| World News | 76 | BBC, CNN, Guardian, NYT, Al Jazeera, Reuters |
| Business/Finance | 25 | CNBC, Fortune, Financial Times, Bloomberg |
| Science/Tech | 9 | Wired, Science Alert, New Scientist, Space.com |
| Israel | 9 | Times of Israel, Jerusalem Post, Haaretz |
| India | 8 | Times of India, The Hindu, India Today |
| French (RFI) | 8 | RFI Africa, Americas, Asia, Europe |
| Germany | 8 | Der Spiegel, Handelsblatt, Tagesspiegel |
| Korea | 8 | Korea Times, Korea Herald |
| Latin America | 5 | O Globo, G1, La Nación |
| Singapore | 1 | Various Singapore sources |

### Sample RSS Feeds:
```
http://feeds.bbci.co.uk/news/rss.xml
http://rss.cnn.com/rss/edition_world.rss
https://www.theguardian.com/world/rss
https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/section/world/rss.xml
https://oglobo.globo.com/rss/
http://g1.globo.com/dynamo/rss2.xml
https://www.wired.com/feed/rss
https://www.cnbc.com/id/100727362/device/rss/rss.html
```

**Status**: All 157 feeds preserved in [rssfeeds.conf](rssfeeds.conf)

---

## 2. NewsAPI Sources (118 sources)

**File**: `newsapi_sources_recovered.json` (newly created)

### Distribution by Language:

| Language | Count | Key Sources |
|----------|-------|-------------|
| English | 79 | BBC, ABC, Associated Press, Reuters, CNN, Axios |
| German | 10 | Der Spiegel, Die Zeit, Focus, Wirtschafts Woche |
| Spanish | 7 | El Mundo, La Nación, Marca |
| French | 5 | Le Monde, Les Échos, Libération |
| Portuguese | 4 | Globo, O Público, InfoMoney |
| Italian | 4 | ANSA, La Repubblica, La Stampa |
| Russian | 4 | RT, Lenta.ru, RBC |
| Arabic | 3 | Al Jazeera Arabic, Argaam |
| Chinese | 2 | Xinhua, People's Daily |

### Distribution by Category:

| Category | Count | Description |
|----------|-------|-------------|
| General News | 66 | Breaking news, world events |
| Technology | 14 | Tech news, startups, innovation |
| Business | 13 | Markets, finance, economics |
| Sports | 13 | Sports coverage |
| Entertainment | 8 | Entertainment, pop culture |
| Science | 3 | Scientific discoveries |
| Health | 1 | Health news |

### Distribution by Country:

| Country | Count | Key Sources |
|---------|-------|-------------|
| USA | 55 | ABC, CBS, NBC, CNN, Fox, Axios, Wired |
| Germany | 10 | Der Spiegel, Die Zeit, Handelsblatt |
| UK | 9 | BBC, Independent, Mirror, Metro |
| Italy | 5 | ANSA, La Repubblica, Il Sole 24 |
| France | 5 | Le Monde, L'Équipe, Libération |
| Australia | 4 | ABC News AU, News.com.au, SMH |
| Canada | 4 | CBC, CTV, National Post |
| Brazil | 4 | Globo, InfoMoney |
| Argentina | 4 | La Nación, Clarín |
| Russia | 4 | RT, Lenta, RBC |

**Status**: ✅ Recovered from live API and saved to `newsapi_sources_recovered.json`

---

## 3. Database Schema

### Table: `gm_sources`

```sql
CREATE TABLE gm_sources (
    id_source TEXT PRIMARY KEY,           -- Unique source ID (16-char hash)
    name TEXT,                             -- Source name
    description TEXT,                      -- Source description
    url TEXT,                              -- Source URL
    category TEXT,                         -- Category (business, tech, general, etc.)
    language TEXT,                         -- Language code (en, pt, es, etc.)
    country TEXT                           -- Country code (us, br, de, etc.)
);
```

### Table: `gm_articles`

```sql
CREATE TABLE gm_articles (
    id_article TEXT PRIMARY KEY,          -- Unique article ID (16-char hash)
    id_source TEXT,                        -- Foreign key to gm_sources
    author TEXT,                           -- Article author
    title TEXT,                            -- Article title
    description TEXT,                      -- Article description
    url TEXT UNIQUE,                       -- Article URL (unique)
    urlToImage TEXT,                       -- Article image URL
    publishedAt TIMESTAMP,                 -- Publication timestamp
    content TEXT,                          -- Article content
    FOREIGN KEY (id_source) REFERENCES gm_sources(id_source)
);
```

---

## 4. Recovery Steps

### Step 1: Create Database

```bash
# On hercules (local machine)
sudo -u postgres createdb -p 5432 predator3_dev
sudo -u postgres psql -p 5432 -d predator3_dev -c "CREATE USER predator WITH PASSWORD 'fuckyou';"
sudo -u postgres psql -p 5432 -d predator3_dev -c "GRANT ALL PRIVILEGES ON DATABASE predator3_dev TO predator;"
```

### Step 2: Create Tables

```bash
python3 << 'EOF'
from sqlalchemy import create_engine, Table, Column, MetaData, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP

conn_string = 'postgresql://predator:fuckyou@localhost:5432/predator3_dev'
engine = create_engine(conn_string)
meta = MetaData()

# Create gm_sources table
gm_sources = Table(
    'gm_sources', meta,
    Column('id_source', Text, primary_key=True),
    Column('name', Text),
    Column('description', Text),
    Column('url', Text),
    Column('category', Text),
    Column('language', Text),
    Column('country', Text)
)

# Create gm_articles table  
gm_articles = Table(
    'gm_articles', meta,
    Column('id_article', Text, primary_key=True),
    Column('id_source', Text),
    Column('author', Text),
    Column('title', Text),
    Column('description', Text),
    Column('url', Text, unique=True),
    Column('urlToImage', Text),
    Column('publishedAt', TIMESTAMP),
    Column('content', Text)
)

meta.create_all(engine)
print("✅ Tables created successfully")
EOF
```

### Step 3: Populate NewsAPI Sources

```bash
python3 << 'EOF'
import json
import base64
import zlib
from sqlalchemy import create_engine, Table, MetaData
from sqlalchemy.dialects.postgresql import insert

def url_encode(url):
    return base64.urlsafe_b64encode(zlib.compress(url.encode('utf-8')))[15:31].decode('utf-8')

conn_string = 'postgresql://predator:fuckyou@localhost:5432/predator3_dev'
engine = create_engine(conn_string)
meta = MetaData()
gm_sources = Table('gm_sources', meta, autoload_with=engine)

# Load NewsAPI sources
with open('newsapi_sources_recovered.json') as f:
    sources = json.load(f)

conn = engine.connect()
for source in sources:
    source_id = url_encode(source['url'])
    stmt = insert(gm_sources).values(
        id_source=source_id,
        name=source['name'],
        description=source.get('description', ''),
        url=source['url'],
        category=source.get('category', ''),
        language=source.get('language', ''),
        country=source.get('country', '')
    ).on_conflict_do_nothing(index_elements=['id_source'])
    conn.execute(stmt)
    conn.commit()

print(f"✅ Inserted {len(sources)} NewsAPI sources")
EOF
```

### Step 4: Populate RSS Sources

```bash
python3 << 'EOF'
import json
import base64
import zlib
from sqlalchemy import create_engine, Table, MetaData
from sqlalchemy.dialects.postgresql import insert

def url_encode(url):
    return base64.urlsafe_b64encode(zlib.compress(url.encode('utf-8')))[15:31].decode('utf-8')

conn_string = 'postgresql://predator:fuckyou@localhost:5432/predator3_dev'
engine = create_engine(conn_string)
meta = MetaData()
gm_sources = Table('gm_sources', meta, autoload_with=engine)

# Load RSS feeds
with open('rssfeeds.conf') as f:
    feeds = json.load(f)

conn = engine.connect()
for feed in feeds:
    source_id = url_encode(feed['url'])
    # Extract source name from URL
    from urllib.parse import urlparse
    parsed = urlparse(feed['url'])
    name = feed.get('label') or parsed.netloc
    
    stmt = insert(gm_sources).values(
        id_source=source_id,
        name=name,
        description='',
        url=feed['url'],
        category='RSS',
        language='',
        country=''
    ).on_conflict_do_nothing(index_elements=['id_source'])
    conn.execute(stmt)
    conn.commit()

print(f"✅ Inserted {len(feeds)} RSS sources")
EOF
```

### Step 5: Verify Database

```bash
sudo -u postgres psql -p 5432 -d predator3_dev -c "\dt"
sudo -u postgres psql -p 5432 -d predator3_dev -c "SELECT COUNT(*) FROM gm_sources;"
sudo -u postgres psql -p 5432 -d predator3_dev -c "SELECT name, category, language, country FROM gm_sources LIMIT 10;"
```

---

## 5. Update Code Configuration

### Fix Database Host in Code

The code references host `titan` but PostgreSQL is on `localhost` (hercules):

**Files to update:**
- `wxAsyncNewsGather.py`
- `wxAsyncNewsReaderv2.py` through `wxAsyncNewsReaderv5.py`
- Any other files with `dbCredentials()`

**Change:**
```python
# OLD
conn_cred = { 
    'user' : 'predator' , 
    'password' : 'fuckyou' , 
    'host' : 'titan',              # ❌ Wrong host
    'dbname' : 'predator3_dev' 
}

# NEW
conn_cred = { 
    'user' : 'predator' , 
    'password' : 'fuckyou' , 
    'host' : 'localhost',          # ✅ Correct host
    'dbname' : 'predator3_dev' 
}
```

---

## 6. Test Recovery

### Test NewsAPI Integration

```bash
python3 wxAsyncNewsGather.py
# Should fetch news and populate gm_articles table
```

### Test RSS Integration

```bash
# Create RSS processor (needs integration work)
python3 rss_task.py
```

### Test GUI

```bash
python3 wxAsyncNewsReaderv5.py
# Should display news from database
```

---

## 7. Outstanding Issues

### RSS Integration
- ❌ RSS feeds in `rssfeeds.conf` are NOT integrated with PostgreSQL
- ❌ `rss_task.py` only stores state in JSON, not in database
- ✅ Need to modify `rss_task.py` to insert articles into `gm_articles` table

### Dead/Broken Sources
- ⚠️ Some RSS feeds from 2020 may no longer work (HTTP-only, FeedBurner deprecated)
- ⚠️ Should audit and remove dead feeds

### Rate Limiting
- ⚠️ NewsAPI: 400 requests/day (currently need 576/day for 4 languages)
- ⚠️ Consider RSS feeds as primary source to reduce API calls

---

## 8. Recommended Next Actions

1. **Create database** (Step 1-2)
2. **Populate sources** (Step 3-4)
3. **Fix host configuration** in Python files (Step 5)
4. **Test NewsAPI collection** (Step 6)
5. **Integrate RSS with database** (requires code changes)
6. **Audit dead feeds** (test and remove broken URLs)
7. **Optimize rate limiting** (prioritize RSS over NewsAPI)

---

## Files Created

- ✅ `newsapi_sources_recovered.json` - 118 NewsAPI sources  
- ✅ `DATABASE_RECOVERY.md` - This recovery document
- ✅ `rssfeeds.conf` - 157 RSS feeds (already existed)

---

## Summary

**Total Recoverable Sources**: 275+ (118 NewsAPI + 157 RSS)  
**Database Status**: Ready for reconstruction  
**Data Loss**: Only historical articles lost, all source configurations recovered  
**Recommendation**: Execute recovery steps 1-4 to restore database functionality

---

**Recovery completed by**: GitHub Copilot  
**Date**: 2026-02-26
