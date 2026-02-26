#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mastodon Real-Time Stream Collector
Replacement for Twitter streaming - FREE and open-source!

Created: 2026-02-26
Author: jamaj
"""

import asyncio
import json
import redis
import base64
import zlib
from datetime import datetime
from decouple import config
from mastodon import Mastodon, StreamListener

# Load configuration from .env
MASTODON_INSTANCE = config('MASTODON_INSTANCE', default='https://mastodon.social')
MASTODON_ACCESS_TOKEN = config('MASTODON_ACCESS_TOKEN', default='')
REDIS_HOST = config('REDIS_HOST', default='localhost')
REDIS_PORT = config('REDIS_PORT', default=6379, cast=int)
REDIS_DB = config('REDIS_DB', default=0, cast=int)

# Connect to Redis
conn = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)


def url_encode(url):
    """Create 16-char unique hash"""
    return base64.urlsafe_b64encode(zlib.compress(url.encode('utf-8')))[15:31].decode('utf-8')


def create_user(conn, user_id, username, display_name='', avatar='', followers=0, following=0, statuses=0):
    """Store Mastodon user in Redis"""
    username_lower = username.lower()
    
    # Check if user exists
    if conn.hexists('users', username_lower):
        existing_id = conn.hget('users', username_lower)
        return existing_id.decode('utf-8')
    
    # Store new user
    conn.hset('users', username_lower, user_id)
    
    user_data = {
        'id': user_id,
        'username': username,
        'display_name': display_name,
        'avatar': avatar,
        'followers_count': followers,
        'following_count': following,
        'statuses_count': statuses,
        'created_at': datetime.now().isoformat()
    }
    
    conn.hset(f'user:{user_id}', mapping=user_data)
    print(f"✅ Created user: @{username} (ID: {user_id})")
    return user_id


def create_status(conn, user_id, status_id, content, data):
    """Store Mastodon toot/status in Redis"""
    # Check if status exists
    if conn.exists(f'status:{status_id}'):
        print(f"⚠️  Status {status_id} already exists")
        return status_id
    
    status_data = {
        'id': status_id,
        'user_id': user_id,
        'content': content,
        'data': json.dumps(data),
        'created_at': data.get('created_at', datetime.now().isoformat())
    }
    
    conn.hset(f'status:{status_id}', mapping=status_data)
    
    # Add to timeline (sorted set by timestamp)
    timestamp = datetime.now().timestamp()
    conn.zadd('timeline', {status_id: timestamp})
    
    print(f"✅ Stored status: {status_id}")
    return status_id


class NewsStreamListener(StreamListener):
    """
    Custom Mastodon stream listener for real-time news collection
    Filters: news, breaking, urgent, alert keywords
    """
    
    def __init__(self):
        super().__init__()
        self.status_count = 0
        
        # News-related keywords to filter
        self.news_keywords = [
            'breaking', 'urgent', 'alert', 'news', 'report',
            'announce', 'update', 'developing', 'confirmed',
            'notícia', 'urgente', 'alerta', 'breaking news'
        ]
    
    def on_update(self, status):
        """Called when a new status (toot) appears"""
        try:
            # Get account info
            account = status['account']
            user_id = str(account['id'])
            username = account['username']
            display_name = account.get('display_name', username)
            avatar = account.get('avatar', '')
            followers = account.get('followers_count', 0)
            following = account.get('following_count', 0)
            statuses = account.get('statuses_count', 0)
            
            # Get status info
            status_id = str(status['id'])
            content = status.get('content', '')
            created_at = status.get('created_at', datetime.now().isoformat())
            
            # Remove HTML tags for display
            import re
            content_text = re.sub('<[^<]+?>', '', content)
            
            # Filter: skip if not news-related
            content_lower = content_text.lower()
            is_news = any(keyword in content_lower for keyword in self.news_keywords)
            
            if not is_news and self.status_count > 0:
                # Only show message every 100 skipped
                if self.status_count % 100 == 0:
                    print(f"⏭️  Skipped {self.status_count} non-news toots...")
                return
            
            # Skip reblogs (retweets)
            if status.get('reblog'):
                print(f"⏭️  Skipped reblog from @{username}")
                return
            
            # Skip replies (optional - you can enable these)
            if status.get('in_reply_to_id'):
                print(f"⏭️  Skipped reply from @{username}")
                return
            
            # Store user
            uid = create_user(
                conn, 
                user_id, 
                username, 
                display_name, 
                avatar, 
                followers, 
                following, 
                statuses
            )
            
            # Store status
            status_data = {
                'id': status_id,
                'account': account,
                'content': content,
                'created_at': created_at,
                'url': status.get('url', ''),
                'language': status.get('language', 'unknown'),
                'visibility': status.get('visibility', 'public'),
                'replies_count': status.get('replies_count', 0),
                'reblogs_count': status.get('reblogs_count', 0),
                'favourites_count': status.get('favourites_count', 0)
            }
            
            sid = create_status(conn, uid, status_id, content_text, status_data)
            
            self.status_count += 1
            
            # Display message
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n{timestamp} | @{username} ({display_name})")
            print(f"Followers: {followers} | Status: {status_id}")
            print(f"Content: {content_text[:200]}...")
            print(f"URL: {status.get('url', 'N/A')}")
            print(f"Total collected: {self.status_count}")
            print("-" * 80)
            
        except Exception as e:
            print(f"❌ Error processing status: {e}")
            import traceback
            traceback.print_exc()
    
    def on_notification(self, notification):
        """Called when a notification arrives"""
        # You can handle notifications here if needed
        pass
    
    def on_delete(self, status_id):
        """Called when a status is deleted"""
        print(f"🗑️  Status deleted: {status_id}")
        # Optional: remove from Redis
        conn.delete(f'status:{status_id}')


def setup_mastodon_client():
    """Initialize Mastodon client with credentials"""
    
    if not MASTODON_ACCESS_TOKEN:
        print("\n" + "=" * 60)
        print("⚠️  MASTODON SETUP REQUIRED")
        print("=" * 60)
        print("\nNo access token found in .env file.")
        print("\nTo get started:")
        print("1. Choose a Mastodon instance (e.g., mastodon.social)")
        print("2. Create an account if you don't have one")
        print("3. Go to Settings → Development → New Application")
        print("4. Create app with these scopes: read, write (optional)")
        print("5. Copy the 'Your access token' value")
        print("6. Add to .env file:")
        print("   MASTODON_INSTANCE=https://mastodon.social")
        print("   MASTODON_ACCESS_TOKEN=your_token_here")
        print("\nAlternatively, run this script to generate token:")
        print("   python3 mastodon_setup.py")
        print("=" * 60)
        return None
    
    try:
        mastodon = Mastodon(
            access_token=MASTODON_ACCESS_TOKEN,
            api_base_url=MASTODON_INSTANCE
        )
        
        # Verify credentials
        account = mastodon.account_verify_credentials()
        print(f"\n✅ Connected to {MASTODON_INSTANCE}")
        print(f"✅ Logged in as: @{account['username']}")
        print(f"   Display name: {account['display_name']}")
        print(f"   Account ID: {account['id']}")
        print(f"   Followers: {account['followers_count']}")
        print()
        
        return mastodon
        
    except Exception as e:
        print(f"\n❌ Failed to connect to Mastodon: {e}")
        print(f"   Instance: {MASTODON_INSTANCE}")
        print("   Check your MASTODON_ACCESS_TOKEN in .env file")
        return None


def start_streaming():
    """Start streaming from Mastodon public timeline"""
    
    mastodon = setup_mastodon_client()
    if not mastodon:
        return
    
    print("=" * 80)
    print("🚀 MASTODON REAL-TIME STREAM COLLECTOR")
    print("=" * 80)
    print(f"Instance: {MASTODON_INSTANCE}")
    print(f"Redis: {REDIS_HOST}:{REDIS_PORT} (db={REDIS_DB})")
    print("\nStreaming from public timeline...")
    print("Filtering: News-related keywords only")
    print("Press Ctrl+C to stop")
    print("=" * 80)
    print()
    
    listener = NewsStreamListener()
    
    try:
        # Stream public timeline
        # Options:
        # - public(): Local + federated timeline
        # - local(): Local instance only
        # - hashtag(tag): Specific hashtag
        # - user(): User's home timeline (requires auth)
        
        print("🎧 Listening to public timeline...\n")
        mastodon.stream_public(listener, run_async=False, reconnect_async=False)
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Stream stopped by user")
        print(f"Total statuses collected: {listener.status_count}")
        
    except Exception as e:
        print(f"\n❌ Stream error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print(" MASTODON STREAM COLLECTOR - Twitter Replacement")
    print(" Free, Open-Source, Real-Time Social Media Streaming")
    print("=" * 80)
    
    # Test Redis connection
    try:
        conn.ping()
        print(f"✅ Redis connected: {REDIS_HOST}:{REDIS_PORT}")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("   Make sure Redis is running: sudo systemctl start redis")
        exit(1)
    
    # Start streaming
    start_streaming()
