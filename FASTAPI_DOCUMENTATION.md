# wxAsyncNewsGather with FastAPI Integration

## Overview

This is a completely rebuilt version of wxAsyncNewsGather that integrates news collection and API serving in a single unified application using FastAPI. Both the news collector and API server run as separate async tasks in the same process, sharing database access efficiently.

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│         wxAsyncNewsGatherAPI.py (Main Process)              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────┐      ┌──────────────────────────┐  │
│  │  FastAPI Server    │      │  News Collector Tasks    │  │
│  │  (Async Task)      │      │  (Async Tasks)           │  │
│  ├────────────────────┤      ├──────────────────────────┤  │
│  │ • /api/articles    │      │ • collect_newsapi()      │  │
│  │ • /api/sources     │      │ • collect_rss_feeds()    │  │
│  │ • /api/stats       │      │ • collect_mediastack()   │  │
│  │ • /api/health      │      │                           │  │
│  │ • /api/latest_ts   │      │ Runs continuously in     │  │
│  │                     │      │ parallel with API        │  │
│  └────────────────────┘      └──────────────────────────┘  │
│           │                            │                    │
│           └──────────┬─────────────────┘                    │
│                      ▼                                       │
│            ┌──────────────────┐                             │
│            │ SQLite Database  │                             │
│            │ predator_news.db │                             │
│            └──────────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

### Components

1. **FastAPI Server**: Handles HTTP API requests on port 8765
2. **News Collector Tasks**: Three parallel tasks collecting from NewsAPI, RSS feeds, and MediaStack
3. **Shared Database**: SQLite database with `inserted_at_ms` timestamp column for efficient queries

### Key Improvements

- ✅ **FastAPI instead of Flask**: Modern async framework with automatic OpenAPI docs
- ✅ **Unified Process**: Both collector and API in same process with proper async coordination
- ✅ **Better Performance**: No separate Flask process, lower overhead
- ✅ **Auto Documentation**: Interactive API docs at `/docs` (Swagger UI)
- ✅ **Type Safety**: Pydantic models and FastAPI validation
- ✅ **Production Ready**: Uvicorn server with proper async handling

## API Endpoints

### 1. GET `/`

Root endpoint with API information and endpoint list.

**Response:**

```json
{
  "name": "wxNews API",
  "version": "2.0.0",
  "status": "running",
  "collector_status": "active",
  "endpoints": {...},
  "documentation": "/docs"
}
```

### 2. GET `/api/health`

Health check endpoint for monitoring.

**Response:**

```json
{
  "status": "ok",
  "timestamp": 1742535600000,
  "version": "2.0.0",
  "collector_running": true,
  "database": "connected"
}
```

### 3. GET `/api/articles`

Get articles inserted after a specific timestamp.

**Parameters:**

- `since` (required): Timestamp in milliseconds
- `limit` (optional): Max articles to return (default: 100, max: 200)
- `sources` (optional): Comma-separated source IDs

**Example:**

```bash
curl "http://localhost:8765/api/articles?since=1742535000000&limit=50"
```

**Response:**

```json
{
  "success": true,
  "count": 15,
  "since": 1742535000000,
  "latest_timestamp": 1742535900000,
  "articles": [
    {
      "id_article": "abc123",
      "id_source": "bbc-news",
      "author": "BBC News",
      "title": "Breaking News...",
      "description": "Full description...",
      "url": "https://...",
      "urlToImage": "https://...",
      "publishedAt": "2026-03-15T10:30:00Z",
      "published_at_gmt": "2026-03-15 10:30:00",
      "inserted_at_ms": 1742535900000
    },
    ...
  ],
  "timestamp": 1742535900500
}
```

### 4. GET `/api/latest_timestamp`

Get the latest insertion timestamp for sync initialization.

**Response:**

```json
{
  "success": true,
  "latest_timestamp": 1742535900000,
  "total_articles": 230793,
  "timestamp": 1742535900500
}
```

### 5. GET `/api/sources`

Get list of available news sources with article counts.

**Response:**

```json
{
  "success": true,
  "count": 150,
  "sources": [
    {
      "id_source": "bbc-news",
      "name": "BBC News",
      "category": "general",
      "language": "en",
      "article_count": 5234
    },
    ...
  ]
}
```

### 6. GET `/api/stats`

Get collection statistics and top sources.

**Response:**

```json
{
  "success": true,
  "total_articles": 230793,
  "articles_last_24h": 1523,
  "articles_last_hour": 63,
  "total_sources": 150,
  "collection_rate_per_hour": 63.0,
  "top_sources_24h": [
    {
      "id_source": "reuters",
      "name": "Reuters",
      "count": 234
    },
    ...
  ],
  "timestamp": 1742535900500
}
```

## Installation

### 1. Install Dependencies

```bash
# Install FastAPI and related packages
pip install -r requirements-fastapi.txt

# Or install individually:
pip install fastapi uvicorn[standard] pydantic fastapi-cors aiohttp sqlalchemy python-decouple
```

### 2. Database Setup

The database should already have the `inserted_at_ms` column from the previous migration. If not:

```bash
python3 add_inserted_timestamp.py
```

### 3. Configuration

Create or update `.env` file:

```bash
# API Configuration
NEWS_API_PORT=8765
NEWS_API_HOST=0.0.0.0

# Database
DB_PATH=predator_news.db

# NewsAPI Keys (existing)
NEWS_API_KEY1=your_key_1
NEWS_API_KEY2=your_key_2

# MediaStack (existing)
MEDIASTACK_API_KEY=your_key

# Intervals (existing)
NEWSAPI_CYCLE_INTERVAL=600
RSS_CYCLE_INTERVAL=600
MEDIASTACK_CYCLE_INTERVAL=900
```

## Running the Application

### Manual Start (Development)

```bash
python3 wxAsyncNewsGatherAPI.py
```

You should see:

```text
╔═══════════════════════════════════════════════════════════╗
║        wxAsyncNewsGather with FastAPI Integration         ║
╠═══════════════════════════════════════════════════════════╣
║  API Server: http://0.0.0.0:8765                          ║
║  Database: /home/jamaj/src/python/pyTweeter/predator_...  ║
║                                                            ║
║  Services:                                                 ║
║    • News Collector (async task)                           ║
║    • FastAPI Server (async task)                           ║
...
╚═══════════════════════════════════════════════════════════╝

INFO:     Started server process [12345]
INFO:     Waiting for application startup.
📊 Database initialized: /home/jamaj/src/python/pyTweeter/predator_news.db
📰 Starting news collector service...
🚀 Starting all news collectors in parallel...
✅ News collector task started
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8765 (Press CTRL+C to quit)
```

### Systemd Service (Production)

```bash
# Install service file
sudo cp wxAsyncNewsGatherAPI.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable wxAsyncNewsGatherAPI.service

# Start service
sudo systemctl start wxAsyncNewsGatherAPI.service

# Check status
sudo systemctl status wxAsyncNewsGatherAPI.service

# View logs
sudo journalctl -u wxAsyncNewsGatherAPI.service -f
```

### Stop Old Services (if running)

If you had the old separate services running:

```bash
# Stop old collector service
sudo systemctl stop wxAsyncNewsGather.service
sudo systemctl disable wxAsyncNewsGather.service

# Stop old Flask API (if any)
sudo systemctl stop wxNewsAPI.service
sudo systemctl disable wxNewsAPI.service
```

## Testing

### Run Test Suite

```bash
python3 test_fastapi_news.py
```

The test suite will:

1. Check health endpoint
2. Get latest timestamp
3. List sources
4. Get statistics
5. Fetch articles
6. Simulate real-time polling

### Manual API Testing

```bash
# Check API is running
curl http://localhost:8765/api/health

# Get latest timestamp
curl http://localhost:8765/api/latest_timestamp

# Get recent articles
TIMESTAMP=$(curl -s http://localhost:8765/api/latest_timestamp | jq -r '.latest_timestamp')
curl "http://localhost:8765/api/articles?since=$((TIMESTAMP - 3600000))&limit=10"

# Get collection stats
curl http://localhost:8765/api/stats
```

### Interactive API Documentation

FastAPI provides automatic interactive documentation:

- **Swagger UI**: <http://localhost:8765/docs>
- **ReDoc**: <http://localhost:8765/redoc>

You can test all endpoints directly from the browser!

## Integration with wxNewsReader

### Polling Pattern

```python
import requests
import time

class NewsAPIClient:
    def __init__(self, api_url="http://localhost:8765"):
        self.api_url = api_url
        self.last_timestamp = self.get_initial_timestamp()
    
    def get_initial_timestamp(self):
        """Get initial sync point"""
        response = requests.get(f"{self.api_url}/api/latest_timestamp")
        data = response.json()
        return data.get('latest_timestamp', 0)
    
    def poll_new_articles(self, limit=100):
        """Poll for new articles since last check"""
        params = {
            'since': self.last_timestamp,
            'limit': limit
        }
        response = requests.get(f"{self.api_url}/api/articles", params=params)
        data = response.json()
        
        if data.get('success'):
            # Update last timestamp
            self.last_timestamp = data.get('latest_timestamp')
            return data.get('articles', [])
        return []

# Usage
client = NewsAPIClient()

while True:
    new_articles = client.poll_new_articles()
    if new_articles:
        print(f"Found {len(new_articles)} new articles")
        # Process articles...
    time.sleep(10)  # Poll every 10 seconds
```

### Async Polling (for wxPython)

```python
import wx
import requests
from threading import Thread

class NewsReaderFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="News Reader")
        self.api_url = "http://localhost:8765"
        self.last_timestamp = 0
        
        # Start polling timer
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_poll_timer, self.timer)
        self.timer.Start(10000)  # 10 seconds
        
        # Initial sync
        self.initial_sync()
    
    def initial_sync(self):
        """Get initial timestamp"""
        def fetch():
            response = requests.get(f"{self.api_url}/api/latest_timestamp")
            data = response.json()
            wx.CallAfter(self.set_timestamp, data.get('latest_timestamp', 0))
        Thread(target=fetch, daemon=True).start()
    
    def set_timestamp(self, timestamp):
        self.last_timestamp = timestamp
    
    def on_poll_timer(self, event):
        """Poll for new articles"""
        def fetch():
            params = {'since': self.last_timestamp, 'limit': 50}
            response = requests.get(f"{self.api_url}/api/articles", params=params)
            data = response.json()
            if data.get('success'):
                wx.CallAfter(self.handle_new_articles, data)
        Thread(target=fetch, daemon=True).start()
    
    def handle_new_articles(self, data):
        """Handle new articles on main thread"""
        articles = data.get('articles', [])
        if articles:
            print(f"Received {len(articles)} new articles")
            self.last_timestamp = data.get('latest_timestamp')
            # Update UI with new articles...
```

## Monitoring

### Check Service Status

```bash
# Service status
sudo systemctl status wxAsyncNewsGatherAPI.service

# Recent logs
sudo journalctl -u wxAsyncNewsGatherAPI.service -n 100

# Follow logs
sudo journalctl -u wxAsyncNewsGatherAPI.service -f

# Logs since today
sudo journalctl -u wxAsyncNewsGatherAPI.service --since today
```

### Database Queries

```bash
# Check recent articles
sqlite3 predator_news.db "
  SELECT COUNT(*), MAX(inserted_at_ms)
  FROM gm_articles
  WHERE inserted_at_ms > (strftime('%s', 'now') - 3600) * 1000
"

# Check collection rate
sqlite3 predator_news.db "
  SELECT 
    strftime('%Y-%m-%d %H:00', datetime(inserted_at_ms/1000, 'unixepoch', 'localtime')) AS hour,
    COUNT(*) AS articles
  FROM gm_articles
  WHERE inserted_at_ms > (strftime('%s', 'now') - 86400) * 1000
  GROUP BY hour
  ORDER BY hour DESC
"
```

### API Health Monitoring

```bash
# Simple health check
curl -f http://localhost:8765/api/health || echo "API DOWN"

# Check collector status
curl -s http://localhost:8765/api/health | jq -r '.collector_running'

# Get stats
curl -s http://localhost:8765/api/stats | jq
```

## Troubleshooting

### API Not Responding

```bash
# Check if process is running
ps aux | grep wxAsyncNewsGatherAPI

# Check if port is listening
sudo netstat -tulpn | grep 8765

# Check logs
sudo journalctl -u wxAsyncNewsGatherAPI.service -n 50
```

### Collector Not Running

Check the `collector_running` status:

```bash
curl http://localhost:8765/api/health | jq '.collector_running'
```

If false, check logs for errors in the collector tasks.

### Database Locked Errors

The unified process reduces database locking, but if you still see errors:

1. Check for other processes accessing the database:

```bash
fuser predator_news.db
```

2. Increase timeout in database connection (already set to 30s)

### High CPU Usage

FastAPI with uvicorn is more efficient than Flask, but if CPU is high:

1. Check collection intervals in `.env`
2. Reduce concurrent workers if needed
3. Monitor with: `top -p $(pgrep -f wxAsyncNewsGatherAPI)`

## Performance

### Advantages Over Flask Version

1. **Single Process**: No IPC overhead, shared memory
2. **True Async**: FastAPI and uvicorn are fully async
3. **Lower Memory**: One Python process instead of two
4. **Better Coordination**: Direct access to collector state
5. **Auto Documentation**: Built-in Swagger UI

### Benchmarks

Typical performance on moderate hardware:

- API latency: < 10ms for `/api/health`
- Articles query: < 50ms for 100 articles
- Collection rate: 50-100 articles/hour (depends on sources)
- Memory usage: ~150MB (unified process)
- CPU usage: < 5% average

## Security

### Production Considerations

1. **Firewall**: Restrict access to API port

```bash
sudo ufw allow from 192.168.1.0/24 to any port 8765
```

2. **Reverse Proxy**: Use nginx for SSL termination

```nginx
location /api/ {
    proxy_pass http://localhost:8765/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

3. **Rate Limiting**: Add FastAPI middleware for rate limiting
4. **Authentication**: Add API key validation if exposing publicly

## Migration from Old System

If you're migrating from the separate Flask + collector system:

1. **Stop old services**:

```bash
sudo systemctl stop wxAsyncNewsGather.service wxNewsAPI.service
```

2. **Install new system**:

```bash
pip install -r requirements-fastapi.txt
sudo cp wxAsyncNewsGatherAPI.service /etc/systemd/system/
sudo systemctl daemon-reload
```

3. **Start new service**:

```bash
sudo systemctl enable --now wxAsyncNewsGatherAPI.service
```

4. **Verify**:

```bash
curl http://localhost:8765/api/health
python3 test_fastapi_news.py
```

5. **Update wxNewsReader** to use new endpoints (same API interface)

## Future Enhancements

Potential improvements:

- WebSocket support for real-time push
- GraphQL endpoint
- Redis caching layer
- PostgreSQL support
- Distributed collection with multiple workers
- Machine learning article classification
- Duplicate detection
- Article summarization API

## Support

For issues or questions:

1. Check logs: `sudo journalctl -u wxAsyncNewsGatherAPI.service -f`
2. Run tests: `python3 test_fastapi_news.py`
3. Check API docs: <http://localhost:8765/docs>
4. Verify database: `sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles"`
