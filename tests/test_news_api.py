#!/usr/bin/env python3
"""
Test the News API Server
"""

import requests
import json
import time

API_BASE = "http://localhost:8765"

def test_health():
    """Test health endpoint"""
    print("🏥 Testing /api/health...")
    response = requests.get(f"{API_BASE}/api/health")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {json.dumps(response.json(), indent=2)}")
    print()

def test_latest_timestamp():
    """Test latest timestamp endpoint"""
    print("🕐 Testing /api/latest_timestamp...")
    response = requests.get(f"{API_BASE}/api/latest_timestamp")
    data = response.json()
    print(f"   Status: {response.status_code}")
    print(f"   Latest Timestamp: {data.get('latest_timestamp')}")
    print(f"   Total Articles: {data.get('total_articles'):,}")
    print()
    return data.get('latest_timestamp', 0)

def test_articles(since_ts, limit=10):
    """Test articles endpoint"""
    print(f"📰 Testing /api/articles?since={since_ts}&limit={limit}...")
    response = requests.get(f"{API_BASE}/api/articles?since={since_ts}&limit={limit}")
    data = response.json()
    print(f"   Status: {response.status_code}")
    print(f"   Count: {data.get('count')}")
    
    if data.get('articles'):
        print(f"   Sample articles:")
        for i, article in enumerate(data['articles'][:3], 1):
            print(f"      {i}. [{article['id_source']}] {article['title'][:60]}...")
            print(f"         Inserted: {article['inserted_at_ms']}")
    print()

def test_sources():
    """Test sources endpoint"""
    print("📡 Testing /api/sources...")
    response = requests.get(f"{API_BASE}/api/sources")
    data = response.json()
    print(f"   Status: {response.status_code}")
    print(f"   Total Sources: {data.get('count')}")
    
    if data.get('sources'):
        print(f"   Sample sources:")
        for source in data['sources'][:5]:
            print(f"      • {source['name']} ({source['id_source']}) - {source['article_count']} articles")
    print()

def test_real_time_updates():
    """Test real-time updates by polling"""
    print("🔄 Testing real-time updates (will poll for 10 seconds)...")
    
    # Get current latest timestamp
    response = requests.get(f"{API_BASE}/api/latest_timestamp")
    latest_ts = response.json().get('latest_timestamp', 0)
    print(f"   Starting from timestamp: {latest_ts}")
    
    new_articles = 0
    for i in range(5):  # Poll 5 times
        time.sleep(2)
        response = requests.get(f"{API_BASE}/api/articles?since={latest_ts}&limit=100")
        data = response.json()
        
        if data.get('count', 0) > 0:
            new_articles += data['count']
            print(f"   ✅ Found {data['count']} new articles!")
            latest_ts = data.get('latest_timestamp', latest_ts)
        else:
            print(f"   ⏳ No new articles yet (poll {i+1}/5)")
    
    print(f"\n   Total new articles found: {new_articles}")
    print()

def main():
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║            News API Server Test Suite                     ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    try:
        # Test all endpoints
        test_health()
        latest_ts = test_latest_timestamp()
        test_sources()
        
        # Test article retrieval with old timestamp (should get articles)
        old_ts = latest_ts - (24 * 60 * 60 * 1000)  # 24 hours ago
        test_articles(old_ts, limit=10)
        
        # Test with latest timestamp (should get no articles initially)
        test_articles(latest_ts, limit=10)
        
        # Test real-time polling
        test_real_time_updates()
        
        print("✅ All tests completed!")
        
    except requests.exceptions.ConnectionError:
        print("❌ ERROR: Cannot connect to API server")
        print("   Make sure the server is running:")
        print("   python3 news_api_server.py")
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
