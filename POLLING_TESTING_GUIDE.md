# Real-Time News Polling - Testing Guide

## Overview

The wxNewsReader now supports real-time article updates by polling the FastAPI server for new articles since the last known timestamp. New articles are dynamically inserted at the top of the feed with smooth animations.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    wxNewsReader (GUI)                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Timer (30s) ──▶ Poll API ──▶ /api/articles?since=ts       │
│                        │                                     │
│                        ▼                                     │
│                 Get new articles                            │
│                        │                                     │
│                        ▼                                     │
│            JavaScript DOM Insertion                         │
│            (Insert at top with animation)                   │
│                        │                                     │
│                        ▼                                     │
│                Show notification toast                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              FastAPI Server (wxAsyncNewsGatherAPI)          │
│                                                              │
│  Endpoint: GET /api/articles?since=<ms>&sources=<ids>       │
│  Returns: New articles with inserted_at_ms > since          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                 SQLite Database                             │
│                                                              │
│  Articles table with inserted_at_ms column                  │
│  Index: idx_articles_inserted_ms (DESC)                     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Features

### 1. **Automatic Polling**
- Polls every 30 seconds by default (configurable)
- Only polls when articles are displayed
- Filters by currently selected sources
- Runs in background thread

### 2. **Dynamic Insertion**
- New articles appear at the top (most recent first)
- Smooth fade-in animation
- No page reload required
- Maintains scroll position

### 3. **Visual Feedback**
- Notification toast shows number of new articles
- Toast slides in from right, auto-dismisses after 3 seconds
- New articles have fade-in animation

### 4. **Smart Filtering**
- Only polls for sources currently displayed
- Respects checked sources in sidebar
- Filters out future-scheduled articles

## Configuration

Add to your `.env` file:

```bash
# API Server URL
NEWS_API_URL=http://localhost:8765

# Polling interval in milliseconds (30000 = 30 seconds)
NEWS_POLL_INTERVAL_MS=30000
```

## Testing Steps

### 1. Start the FastAPI Server

```bash
# Option 1: Manual start
python3 wxAsyncNewsGatherAPI.py

# Option 2: Use migration script
./migrate_to_fastapi.sh

# Option 3: Start as service
sudo systemctl start wxAsyncNewsGatherAPI
```

Verify the server is running:
```bash
curl http://localhost:8765/api/health
```

Expected output:
```json
{
  "status": "ok",
  "timestamp": 1742535600000,
  "version": "2.0.0",
  "collector_running": true,
  "database": "connected"
}
```

### 2. Start the News Reader

```bash
# Launch the GUI
python3 wxAsyncNewsReaderv6.py

# Or use the desktop launcher
gtk-launch wxNewsReader.desktop
```

### 3. Monitor the Logs

In the terminal where wxNewsReader is running, you should see:

```
=== Loading Sources ===
Found 150 sources with >= 10 articles
✅ API initialized with timestamp: 1742535600000
🔄 Polling enabled (every 30.0s)
```

If API is not available:
```
⚠️  API not available - polling disabled
```

### 4. Test Polling

**Method 1: Wait for Natural Updates**
1. Select some news sources
2. Click "Load Checked"
3. Wait 30 seconds for new articles to be collected
4. Watch for notification toast and new articles appearing

**Method 2: Force New Articles (Testing)**

Add some test articles manually:
```bash
sqlite3 predator_news.db
```

```sql
INSERT INTO gm_articles (
  id_article, id_source, title, url, 
  published_at_gmt, inserted_at_ms
) VALUES (
  'test-' || strftime('%s', 'now'),
  'bbc-news',
  'Test Article - ' || datetime('now'),
  'http://example.com',
  datetime('now'),
  cast(strftime('%s', 'now') * 1000 as integer)
);
```

### 5. Verify Dynamic Insertion

When new articles arrive:

1. **Notification appears**: "X new article(s) loaded"
2. **Toast animation**: Slides in from right, stays 3 seconds
3. **Article insertion**: New cards appear at top
4. **Smooth animation**: Fade-in effect
5. **No scroll jump**: Current position maintained

### 6. Check Console Logs

Look for these messages:

```
📥 Inserting 3 new articles
```

If polling fails:
```
WARNING:root:Failed to poll new articles: [error details]
```

### 7. Test Edge Cases

**No new articles:**
- Polling continues silently
- No notification shown
- No UI changes

**API unavailable:**
- Polling stops automatically
- Warning logged once
- Reader still works with manual refresh

**Network error during poll:**
- Error logged
- Next poll continues normally
- No UI disruption

## Troubleshooting

### API Not Initializing

**Symptom:** Log shows "API not available - polling disabled"

**Solutions:**
1. Check if FastAPI server is running:
   ```bash
   curl http://localhost:8765/api/health
   ```

2. Check the server logs:
   ```bash
   sudo journalctl -u wxAsyncNewsGatherAPI -f
   ```

3. Verify database has timestamp column:
   ```bash
   sqlite3 predator_news.db "PRAGMA table_info(gm_articles)" | grep inserted_at_ms
   ```

4. Check firewall:
   ```bash
   sudo ufw status
   ```

### No New Articles Appearing

**Symptom:** Polling enabled but no articles inserted

**Solutions:**
1. Check if collector is running:
   ```bash
   curl http://localhost:8765/api/health | jq '.collector_running'
   ```

2. Check collection stats:
   ```bash
   curl http://localhost:8765/api/stats | jq '.articles_last_hour'
   ```

3. Monitor API logs for errors:
   ```bash
   sudo journalctl -u wxAsyncNewsGatherAPI | grep ERROR
   ```

4. Manually test API endpoint:
   ```bash
   TIMESTAMP=$(date -d '1 hour ago' +%s)000
   curl "http://localhost:8765/api/articles?since=$TIMESTAMP&limit=10" | jq
   ```

### JavaScript Not Executing

**Symptom:** Articles don't appear dynamically

**Solutions:**
1. Check WebView console (if available)
2. Verify HTML has `articles-container` div:
   ```bash
   # Look for the container in generated HTML
   grep -o "articles-container" wxAsyncNewsReaderv6.py
   ```

3. Test JavaScript manually:
   - Open browser dev tools
   - Check for JavaScript errors
   - Verify `document.querySelector('.articles-container')` returns element

### High CPU Usage

**Symptom:** wxNewsReader using too much CPU

**Solutions:**
1. Increase polling interval:
   ```bash
   # In .env file
   NEWS_POLL_INTERVAL_MS=60000  # 1 minute
   ```

2. Limit sources:
   - Uncheck some sources
   - Reduce to higher-quality sources only

3. Check for errors in console
   - Look for continuous error loops

## Performance Metrics

Expected performance on moderate hardware:

- **Polling overhead:** < 1% CPU
- **API latency:** 10-50ms
- **Insertion time:** < 100ms for 10 articles
- **Memory increase:** ~5MB per 1000 articles cached
- **Network:** ~5KB per poll (empty), ~50KB per 10 articles

## Advanced Testing

### Load Testing

Test with multiple articles:

```python
# test_insert_multiple.py
import sqlite3
import time

db = sqlite3.connect('predator_news.db')
cursor = db.cursor()

for i in range(20):
    cursor.execute("""
        INSERT INTO gm_articles (
            id_article, id_source, title, url, 
            published_at_gmt, inserted_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        f'test-{int(time.time())}-{i}',
        'bbc-news',
        f'Test Article {i+1}',
        'http://example.com',
        time.strftime('%Y-%m-%d %H:%M:%S'),
        int(time.time() * 1000)
    ))
    time.sleep(0.1)  # Small delay

db.commit()
db.close()
print("✅ Inserted 20 test articles")
```

Run this while wxNewsReader is open to see bulk insertion.

### Performance Monitoring

Monitor in real-time:

```bash
# Watch API stats
watch -n 5 'curl -s http://localhost:8765/api/stats | jq'

# Monitor wxNewsReader process
top -p $(pgrep -f wxAsyncNewsReaderv6)

# Track database size
watch -n 30 'ls -lh predator_news.db'
```

## Next Steps

1. **Integrate with wxNewsReader GUI:**
   - Add polling status indicator
   - Add manual "Check Now" button
   - Show last poll time

2. **Enhanced Features:**
   - WebSocket support for instant push
   - Read/unread article tracking
   - Article bookmarking
   - Offline mode with queue

3. **Performance Optimization:**
   - Implement article deduplication
   - Add local caching layer
   - Lazy image loading
   - Virtual scrolling for large lists

## Support

If issues persist:

1. Check logs: `sudo journalctl -u wxAsyncNewsGatherAPI -f`
2. Test API manually: `python3 test_fastapi_news.py`
3. Verify database: `sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles"`
4. Review documentation: `FASTAPI_DOCUMENTATION.md`
