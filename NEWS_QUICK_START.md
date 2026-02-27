# News System - Quick Start

## 🚀 Quick Start (3 Steps)

### 1. Start the Collector (Background)
```bash
./start_news_collector.sh
```
This runs in the background and collects news every 10 minutes.

### 2. Start the Reader (GUI)
```bash
./start_news_reader.sh
```
This opens a GUI window to browse collected news.

### 3. Browse News!
- Click a source on the left to see its articles
- Click an article to open in your browser

## 🛑 Stop the Collector
```bash
./stop_news_collector.sh
```

## 📖 Full Documentation
See [NEWS_SYSTEM_GUIDE.md](NEWS_SYSTEM_GUIDE.md) for complete documentation.

## 🏗️ Architecture

```
wxAsyncNewsGather.py  →  predator_news.db  →  wxAsyncNewsReader.py
    (Collector)           (SQLite)              (GUI Reader)
```

## ✅ Verification

Check if collector is running:
```bash
ps aux | grep wxAsyncNewsGather
```

View collector logs:
```bash
tail -f collector.log
```

Check database stats:
```bash
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles;"
```

## 📦 News Sources

- **NewsAPI**: EN, PT, ES, IT top headlines
- **RSS Feeds**: 100+ news outlets and tech blogs
- **MediaStack**: 7,500+ global news sources

## 🔧 Configuration

Edit `.env` file to configure:
- API keys
- Update intervals  
- RSS settings
- Database path

## 🎯 Key Files

| File | Purpose |
|------|---------|
| `wxAsyncNewsGather.py` | Background news collector |
| `wxAsyncNewsReader.py` | GUI news reader |
| `predator_news.db` | SQLite database |
| `.env` | Configuration |
| `start_news_collector.sh` | Start collector script |
| `start_news_reader.sh` | Start reader script |
| `stop_news_collector.sh` | Stop collector script |
| `NEWS_SYSTEM_GUIDE.md` | Full documentation |

## 🐛 Troubleshooting

**No articles?**
- Wait 10 minutes for first collection
- Check if collector is running
- Review `collector.log`

**GUI won't start?**
```bash
pip install wxPython wxasync
```

**Database locked?**
- Stop reader, wait for collector cycle, restart reader

## 📝 System Status

Current version: **v5**
- ✅ Separate collector and reader
- ✅ SQLite database (migrated from PostgreSQL)
- ✅ Multi-source collection (NewsAPI + RSS + MediaStack)
- ✅ Robust async processing
- ✅ Auto-refresh every 60 seconds
