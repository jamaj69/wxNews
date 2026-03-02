# News Collection and Reading System Guide

## Overview

The news system consists of two independent components optimized for different purposes:

### 1. **wxAsyncNewsGather.py** - News Collector (No GUI)
A standalone async news collector that runs continuously in the background, gathering news from multiple sources and storing in SQLite database.

**Features:**
- ✅ NewsAPI integration (EN, PT, ES, IT languages)
- ✅ RSS feed collection from 100+ sources 
- ✅ MediaStack API integration (7,500+ news sources)
- ✅ Automatic news updates every 10 minutes
- ✅ Smart rate limiting to stay within API quotas
- ✅ Concurrent async processing for fast collection
- ✅ Robust error handling and logging

**Sources:**
- NewsAPI: Top headlines in 4 languages
- RSS Feeds: Major news outlets, tech blogs, regional sources
- MediaStack: Multilingual news from 50+ countries

### 2. **wxAsyncNewsReader.py** - News Reader (wxPython GUI)
A graphical interface for reading collected news from the database. Does NOT collect news - only displays.

**Features:**
- 📰 Two-panel interface: Sources list + Articles list
- 🔍 Browse articles by source
- 📖 **Detailed article viewer** with full text, images, and metadata
- 🌐 Open articles in web browser
- 🕐 Display article timestamps
- 🔄 Auto-refresh from database every minute
- ⌨️ Keyboard shortcuts (ESC to close detail view)

## Architecture

```
┌─────────────────────────┐
│  wxAsyncNewsGather.py   │  ← Runs in background terminal
│  (Collector/No GUI)     │     Collects news every 10 min
└───────────┬─────────────┘
            │ Writes to
            ▼
   ┌─────────────────┐
   │  predator_news  │  ← SQLite Database
   │     .db         │     (gm_sources + gm_articles)
   └────────┬────────┘
            │ Reads from
            ▼
┌─────────────────────────┐
│  wxAsyncNewsReader.py   │  ← Runs in GUI window
│  (Reader/wxPython GUI)  │     Displays articles
└─────────────────────────┘
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Required packages:
- wxPython (GUI)
- wxasync (Async support for wx)
- aiohttp (Async HTTP)
- sqlalchemy >= 2.0 (Database - uses 2.0+ syntax)
- feedparser (RSS parsing)
- python-decouple (Config management)

### 2. Configuration

All configuration is in `.env` file:

```bash
# Database
DB_PATH=predator_news.db

# NewsAPI Keys (Reader only needs KEY_1)
NEWS_API_KEY_1=your_key_here
NEWS_API_KEY_2=your_key_here    # Used by Collector

# MediaStack API (Used by Collector only)
MEDIASTACK_API_KEY=your_key_here

# RSS Settings
RSS_TIMEOUT=15
RSS_MAX_CONCURRENT=10
RSS_BATCH_SIZE=20

# Update interval (seconds)
UPDATE_INTERVAL_SEC=600
```

## Usage

### Step 1: Start the News Collector (Background)

In one terminal:

```bash
python wxAsyncNewsGather.py
```

You should see logs like:
```
2024-XX-XX XX:XX:XX - INFO - Initializing NewsGather...
2024-XX-XX XX:XX:XX - INFO - Opening SQLite database: predator_news.db
2024-XX-XX XX:XX:XX - INFO - Loaded 50 sources from database
2024-XX-XX XX:XX:XX - INFO - Starting news collection loop
```

**Leave this running!** It will:
- Collect news every 10 minutes
- Update the database automatically
- Run indefinitely until you stop it (Ctrl+C)

### Step 2: Start the News Reader (GUI)

In another terminal:

```bash
python wxAsyncNewsReader.py
```

A GUI window will open with:
- **Left panel**: List of news sources
- **Right panel**: Articles from selected source
- Click on a source to see its articles
- **Click on an article** to open detailed view with:
  - Full title and metadata (author, date, source)
  - Article image (if available)
  - Description and content
  - Button to open full article in browser
- Double-click or use keyboard to navigate

The GUI will auto-refresh every minute to show new articles.

## Tips

### Run Collector in Background (Linux/Mac)

```bash
# Start in background
nohup python wxAsyncNewsGather.py > collector.log 2>&1 &

# Check if running
ps aux | grep wxAsyncNewsGather

# View logs
tail -f collector.log

# Stop background process
pkill -f wxAsyncNewsGather
```

### Run Collector as systemd Service (Linux)

Create `/etc/systemd/system/news-collector.service`:

```ini
[Unit]
Description=News Collector Service
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/pyTweeter
ExecStart=/usr/bin/python3 /path/to/pyTweeter/wxAsyncNewsGather.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable news-collector
sudo systemctl start news-collector
sudo systemctl status news-collector
```

### Troubleshooting

**"Database is locked" error:**
- Both files use `timeout=30` and `check_same_thread=False`
- Should not happen, but if it does:
  - Stop the reader
  - Let collector finish its cycle
  - Restart reader

**No articles appearing:**
- Make sure collector is running
- Wait for first collection cycle (up to 10 minutes)
- Check collector logs for errors
- Verify API keys in `.env`

**Collector stops working:**
- Check API quotas:
  - NewsAPI: 100 requests/day (free tier)
  - MediaStack: 500 requests/month (free tier)
- Check internet connection
- Review logs for error messages

**GUI refresh not working:**
- Reader refreshes from DB every 60 seconds
- If collector isn't running, no new articles will appear
- Click a source to manually refresh article list

## Database Schema

### gm_sources table
```sql
CREATE TABLE gm_sources (
    id_source TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    url TEXT,
    category TEXT,
    language TEXT,
    country TEXT
);
```

### gm_articles table
```sql
CREATE TABLE gm_articles (
    id_article TEXT PRIMARY KEY,  -- Hash of title+url+timestamp
    id_source TEXT,
    author TEXT,
    title TEXT,
    description TEXT,
    url TEXT,
    urlToImage TEXT,
    publishedAt TEXT,
    content TEXT
);
```

## API Quotas

| Service | Free Tier Limit | Collection Strategy |
|---------|-----------------|---------------------|
| NewsAPI | 100 req/day | 4 languages × 6 calls/hour = 96/day |
| MediaStack | 500 req/month | 1 call every 60 min = ~720/month |
| RSS Feeds | Unlimited | 100+ feeds every 10 min |

## Performance

- **Collection cycle**: ~10-30 seconds (depending on sources)
- **Articles collected**: ~500-1000 per cycle
- **Database size**: ~10-50 MB after a week
- **Memory usage**: 
  - Collector: ~150 MB
  - Reader: ~80 MB
- **CPU usage**: Low (~5% during collection)

## Monitoring

Check collector status:
```bash
# View recent logs
tail -100 collector.log

# Count articles in database
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles;"

# Count sources
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_sources;"

# Check latest articles
sqlite3 predator_news.db "SELECT title, publishedAt FROM gm_articles ORDER BY publishedAt DESC LIMIT 10;"
```

## Stopping the System

1. **Stop Reader**: Close the GUI window or Ctrl+C in terminal
2. **Stop Collector**: Ctrl+C in terminal or `pkill -f wxAsyncNewsGather`

## Version History

- **v5 (Current)**: Database-only reader, separate collector
- **v4**: Added TimeStamp column
- **v3**: Improved database handling
- **v2**: Added async collection in reader
- **v1**: Basic Twisted-based reader

## File Structure

```
pyTweeter/
├── wxAsyncNewsGather.py       # Background collector (use this)
├── wxAsyncNewsReader.py        # GUI reader (use this)
├── wxAsyncNewsReaderv2-v5.py  # Historical versions
├── predator_news.db            # SQLite database
├── .env                        # Configuration
├── requirements.txt            # Dependencies
└── NEWS_SYSTEM_GUIDE.md       # This file
```

## Next Steps

1. Start the collector in background
2. Open the reader GUI
3. Browse news!
4. (Optional) Set up systemd service for auto-start on boot

For issues or improvements, check the logs and adjust `.env` settings.
