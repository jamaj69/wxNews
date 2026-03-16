#!/usr/bin/env python3
"""
Test script for wxAsyncNewsGather FastAPI endpoints
"""

import requests
import time
import sys

API_URL = "http://localhost:8765"

def print_section(title):
    """Print a section header"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)

def test_health():
    """Test health endpoint"""
    print_section("Testing Health Endpoint")
    try:
        response = requests.get(f"{API_URL}/api/health", timeout=5)
        response.raise_for_status()
        data = response.json()
        print(f"✅ Health check passed")
        print(f"   Status: {data.get('status')}")
        print(f"   Version: {data.get('version')}")
        print(f"   Collector running: {data.get('collector_running')}")
        print(f"   Database: {data.get('database')}")
        return True
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to API server at {API_URL}")
        print(f"   Make sure the server is running:")
        print(f"   python3 wxAsyncNewsGatherAPI.py")
        return False
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

def test_latest_timestamp():
    """Test latest timestamp endpoint"""
    print_section("Testing Latest Timestamp Endpoint")
    try:
        response = requests.get(f"{API_URL}/api/latest_timestamp", timeout=5)
        response.raise_for_status()
        data = response.json()
        print(f"✅ Latest timestamp retrieved")
        print(f"   Latest timestamp: {data.get('latest_timestamp')}")
        print(f"   Total articles: {data.get('total_articles'):,}")
        return data.get('latest_timestamp', 0)
    except Exception as e:
        print(f"❌ Failed to get latest timestamp: {e}")
        return 0

def test_sources():
    """Test sources endpoint"""
    print_section("Testing Sources Endpoint")
    try:
        response = requests.get(f"{API_URL}/api/sources", timeout=10)
        response.raise_for_status()
        data = response.json()
        sources = data.get('sources', [])
        print(f"✅ Retrieved {len(sources)} sources")
        
        if sources:
            print(f"\n   Top 5 sources by article count:")
            sorted_sources = sorted(sources, key=lambda x: x.get('article_count', 0), reverse=True)
            for i, source in enumerate(sorted_sources[:5], 1):
                print(f"   {i}. {source.get('name')} - {source.get('article_count'):,} articles")
        
        return sources
    except Exception as e:
        print(f"❌ Failed to get sources: {e}")
        return []

def test_stats():
    """Test stats endpoint"""
    print_section("Testing Statistics Endpoint")
    try:
        response = requests.get(f"{API_URL}/api/stats", timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"✅ Statistics retrieved")
        print(f"   Total articles: {data.get('total_articles'):,}")
        print(f"   Articles (24h): {data.get('articles_last_24h'):,}")
        print(f"   Articles (1h): {data.get('articles_last_hour'):,}")
        print(f"   Total sources: {data.get('total_sources')}")
        print(f"   Collection rate: ~{data.get('collection_rate_per_hour'):.1f} articles/hour")
        
        top_sources = data.get('top_sources_24h', [])
        if top_sources:
            print(f"\n   Top sources (last 24h):")
            for i, source in enumerate(top_sources[:5], 1):
                print(f"   {i}. {source.get('name')} - {source.get('count')} articles")
        
        return True
    except Exception as e:
        print(f"❌ Failed to get stats: {e}")
        return False

def test_articles(since_timestamp):
    """Test articles endpoint"""
    print_section("Testing Articles Endpoint")
    try:
        # Test with timestamp from 1 hour ago
        one_hour_ago = int((time.time() - 3600) * 1000)
        test_timestamp = max(since_timestamp - 3600000, one_hour_ago)  # 1 hour ago
        
        params = {
            'since': test_timestamp,
            'limit': 10
        }
        
        response = requests.get(f"{API_URL}/api/articles", params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        articles = data.get('articles', [])
        print(f"✅ Retrieved {len(articles)} articles since timestamp {test_timestamp}")
        print(f"   Latest timestamp: {data.get('latest_timestamp')}")
        
        if articles:
            print(f"\n   First 3 articles:")
            for i, article in enumerate(articles[:3], 1):
                print(f"\n   {i}. {article.get('title', 'No title')[:60]}...")
                print(f"      Source: {article.get('id_source')}")
                print(f"      Inserted: {article.get('inserted_at_ms')}")
                print(f"      URL: {article.get('url', 'No URL')[:60]}")
        else:
            print(f"   ℹ️  No new articles in the last hour")
        
        return data.get('latest_timestamp')
    except Exception as e:
        print(f"❌ Failed to get articles: {e}")
        return since_timestamp

def test_polling(initial_timestamp, duration=30, polls=3):
    """Simulate real-time polling"""
    print_section(f"Testing Real-Time Polling ({polls} polls over {duration}s)")
    
    last_ts = initial_timestamp
    interval = duration // polls
    
    for poll_num in range(1, polls + 1):
        print(f"\n📡 Poll {poll_num}/{polls} (waiting {interval}s)...")
        time.sleep(interval)
        
        try:
            params = {'since': last_ts, 'limit': 100}
            response = requests.get(f"{API_URL}/api/articles", params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            count = data.get('count', 0)
            latest = data.get('latest_timestamp', last_ts)
            
            if count > 0:
                print(f"   ✅ Found {count} new articles")
                articles = data.get('articles', [])
                if articles:
                    first = articles[0]
                    print(f"   Latest: {first.get('title', 'No title')[:50]}...")
                last_ts = latest
            else:
                print(f"   ℹ️  No new articles")
                
        except Exception as e:
            print(f"   ❌ Poll failed: {e}")
    
    print(f"\n✅ Polling test complete")
    return last_ts

def test_root():
    """Test root endpoint"""
    print_section("Testing Root Endpoint")
    try:
        response = requests.get(f"{API_URL}/", timeout=5)
        response.raise_for_status()
        data = response.json()
        print(f"✅ Root endpoint working")
        print(f"   Name: {data.get('name')}")
        print(f"   Version: {data.get('version')}")
        print(f"   Collector status: {data.get('collector_status')}")
        print(f"   Documentation: {API_URL}{data.get('documentation')}")
        return True
    except Exception as e:
        print(f"❌ Root endpoint failed: {e}")
        return False

def main():
    """Run all tests"""
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║          wxAsyncNewsGather FastAPI Test Suite            ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    print(f"Testing API at: {API_URL}")
    print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Test 1: Root endpoint
    if not test_root():
        print("\n❌ Basic connectivity failed. Exiting.")
        sys.exit(1)
    
    # Test 2: Health check
    if not test_health():
        print("\n❌ Health check failed. Is the server running?")
        sys.exit(1)
    
    # Test 3: Latest timestamp
    latest_ts = test_latest_timestamp()
    if latest_ts == 0:
        print("\n⚠️  Database appears empty or timestamp not available")
    
    # Test 4: Sources
    sources = test_sources()
    if not sources:
        print("\n⚠️  No sources available")
    
    # Test 5: Statistics
    test_stats()
    
    # Test 6: Articles
    if latest_ts > 0:
        latest_ts = test_articles(latest_ts)
    
    # Test 7: Real-time polling simulation
    if latest_ts > 0:
        test_polling(latest_ts, duration=30, polls=3)
    
    # Final summary
    print_section("Test Summary")
    print(f"✅ All tests completed")
    print(f"Finished at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n📖 Full API documentation available at: {API_URL}/docs")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑 Tests interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Test suite error: {e}")
        sys.exit(1)
