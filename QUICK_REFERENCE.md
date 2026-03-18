# wxNews - Quick Reference

Fast command reference for common operations.

---

## 🚀 Service Management

### Start/Stop/Status

```bash
# Start service
sudo systemctl start wxAsyncNewsGatherAPI.service

# Stop service
sudo systemctl stop wxAsyncNewsGatherAPI.service

# Restart service
sudo systemctl restart wxAsyncNewsGatherAPI.service

# Status (is it running?)
sudo systemctl status wxAsyncNewsGatherAPI.service

# Enable on boot
sudo systemctl enable wxAsyncNewsGatherAPI.service

# Disable on boot
sudo systemctl disable wxAsyncNewsGatherAPI.service
```

### Logs

```bash
# Real-time logs (follow)
journalctl -u wxAsyncNewsGatherAPI.service -f

# Last 50 lines
journalctl -u wxAsyncNewsGatherAPI.service -n 50

# Last 100 lines
journalctl -u wxAsyncNewsGatherAPI.service -n 100

# Errors only
journalctl -u wxAsyncNewsGatherAPI.service -p err

# Today's logs
journalctl -u wxAsyncNewsGatherAPI.service --since today

# Logs since time
journalctl -u wxAsyncNewsGatherAPI.service --since "2026-03-17 10:00:00"
```

### Update Service Configuration

```bash
# After editing .service file
sudo systemctl daemon-reload
sudo systemctl restart wxAsyncNewsGatherAPI.service
```

---

## 📱 Start GUI

```bash
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate
python wxAsyncNewsReaderv6.py
```

---

## 🔍 Database Queries

### Count Articles

```bash
# Total articles
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles;"

# Articles today
sqlite3 predator_news.db "
SELECT COUNT(*) FROM gm_articles 
WHERE published_at_gmt > unixepoch('now', '-1 day');"

# Articles this week
sqlite3 predator_news.db "
SELECT COUNT(*) FROM gm_articles 
WHERE published_at_gmt > unixepoch('now', '-7 days');"
```

### Recent Articles

```bash
# Last 10 articles
sqlite3 predator_news.db "
SELECT datetime(published_at_gmt, 'unixepoch') as date,
       title,
       source_name
FROM gm_articles
ORDER BY published_at_gmt DESC
LIMIT 10;"

# Last 20 articles with URLs
sqlite3 predator_news.db "
SELECT datetime(published_at_gmt, 'unixepoch') as date,
       title,
       url,
       source_name
FROM gm_articles
ORDER BY published_at_gmt DESC
LIMIT 20;"
```

### Articles by Source

```bash
# Top 20 sources (last 24 hours)
sqlite3 predator_news.db "
SELECT source_name, COUNT(*) as total
FROM gm_articles
WHERE published_at_gmt > unixepoch('now', '-1 day')
GROUP BY source_name
ORDER BY total DESC
LIMIT 20;"

# All sources with article count
sqlite3 predator_news.db "
SELECT source_name, COUNT(*) as total
FROM gm_articles
GROUP BY source_name
ORDER BY total DESC;"
```

### Source Information

```bash
# List all sources
sqlite3 predator_news.db "SELECT id_source, source_name, url FROM gm_sources ORDER BY source_name;"

# Sources with timezone
sqlite3 predator_news.db "
SELECT source_name, timezone, use_timezone
FROM gm_sources
WHERE use_timezone = 1
ORDER BY source_name;"

# Count sources
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_sources;"
```

### Latest Collection Time

```bash
# Last article inserted
sqlite3 predator_news.db "
SELECT datetime(MAX(inserted_at_ms)/1000, 'unixepoch') as last_insert,
       datetime(MAX(published_at_gmt), 'unixepoch') as last_published
FROM gm_articles;"
```

---

## 🌐 API Calls

### Health Check

```bash
curl http://localhost:8765/api/health
```

### Get Latest Timestamp

```bash
curl http://localhost:8765/api/latest_timestamp
```

### Get Articles Since Timestamp

```bash
# Get 50 articles since timestamp
curl "http://localhost:8765/api/articles?since=1710000000000&limit=50"

# Get articles from specific sources
curl "http://localhost:8765/api/articles?since=1710000000000&sources=bbc,cnn,nyt&limit=30"
```

### Get Sources

```bash
curl http://localhost:8765/api/sources
```

### Get Statistics

```bash
curl http://localhost:8765/api/stats
```

### API Documentation

```bash
# Open in browser
firefox http://localhost:8765/docs

# Or
curl http://localhost:8765/docs
```

---

## 🔧 Troubleshooting

### Check if Service is Running

```bash
ps aux | grep wxAsyncNewsGatherAPI
```

### Check Port Usage

```bash
# Is port 8765 in use?
sudo lsof -i :8765

# Or
sudo netstat -tulpn | grep 8765
```

### Test Manual Start

```bash
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate
python wxAsyncNewsGatherAPI.py
```

### Check Environment Variables

```bash
cat .env | grep -v '^#' | grep -v '^$'
```

### Check Database Integrity

```bash
sqlite3 predator_news.db "PRAGMA integrity_check;"
```

### Check Database Size

```bash
ls -lh predator_news.db
```

### Rebuild Database Indexes

```bash
sqlite3 predator_news.db "REINDEX;"
```

---

## 🧹 Cleanup

### Remove Old Articles

```bash
# Delete articles older than 90 days
sqlite3 predator_news.db "
DELETE FROM gm_articles 
WHERE published_at_gmt < unixepoch('now', '-90 days');"

# Vacuum to reclaim space
sqlite3 predator_news.db "VACUUM;"
```

### Remove Duplicates

```bash
# Check for duplicates
sqlite3 predator_news.db "
SELECT url, COUNT(*) as count
FROM gm_articles
GROUP BY url
HAVING count > 1
ORDER BY count DESC
LIMIT 20;"

# Run cleanup script
bash run_cleanup.sh
```

---

## 📊 Statistics

### Timezone Coverage

```bash
python check_gmt_coverage.py
```

### Source Diagnostics

```bash
# Check blocklisted sources
python check_blocklist.py

# Diagnose feed issues
python diagnose_feeds.py

# View broken RSS URLs
cat broken_rss_urls.txt
```

### Collection Stats

```bash
sqlite3 predator_news.db "
SELECT 
    COUNT(*) as total_articles,
    COUNT(DISTINCT id_source) as unique_sources,
    datetime(MIN(published_at_gmt), 'unixepoch') as oldest,
    datetime(MAX(published_at_gmt), 'unixepoch') as newest
FROM gm_articles;"
```

---

## 📝 Quick Tests

### Test NewsAPI Key

```bash
python -c "
from decouple import config
import requests
key = config('NEWS_API_KEY_1')
url = f'https://newsapi.org/v2/top-headlines?country=us&apiKey={key}'
r = requests.get(url)
print(f'Status: {r.status_code}')
print(f'Articles: {len(r.json().get(\"articles\", []))}')
"
```

### Test Database Connection

```bash
python -c "
from sqlalchemy import create_engine, text
eng = create_engine('sqlite:///predator_news.db')
with eng.connect() as conn:
    result = conn.execute(text('SELECT COUNT(*) FROM gm_articles'))
    print(f'Articles in database: {result.scalar()}')
"
```

### Test API Connection

```bash
curl -s http://localhost:8765/api/health | python -m json.tool
```

---

## 📂 File Locations

| Component | Path |
|-----------|------|
| Service file | `/etc/systemd/system/wxAsyncNewsGatherAPI.service` |
| Database | `/home/jamaj/src/python/pyTweeter/predator_news.db` |
| Config | `/home/jamaj/src/python/pyTweeter/.env` |
| Main script | `/home/jamaj/src/python/pyTweeter/wxAsyncNewsGatherAPI.py` |
| GUI | `/home/jamaj/src/python/pyTweeter/wxAsyncNewsReaderv6.py` |
| Python env | `/home/python/pyenv/bin/activate` |

---

## 🔗 Quick Links

- [README.md](README.md) - Main documentation
- [copilot-instructions.md](copilot-instructions.md) - System operations
- [FASTAPI_DOCUMENTATION.md](FASTAPI_DOCUMENTATION.md) - API details
- [docs/README.md](docs/README.md) - Technical docs

---

**Tip**: Bookmark this file for quick access to common commands!

**Last Updated**: March 17, 2026
