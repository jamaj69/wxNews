#!/usr/bin/env python3
"""
Test Twitter/X API Credentials
Tests if the Twitter API v1.1 credentials still work
"""

from decouple import config
import sys

print("=" * 60)
print("Twitter/X API Credentials Test")
print("=" * 60)

# Load credentials from .env
try:
    CONSUMER_KEY = config('TWITTER_CONSUMER_KEY')
    CONSUMER_SECRET = config('TWITTER_CONSUMER_SECRET')
    ACCESS_TOKEN = config('TWITTER_ACCESS_TOKEN')
    ACCESS_TOKEN_SECRET = config('TWITTER_ACCESS_TOKEN_SECRET')
    
    print("\n✅ Credentials loaded from .env:")
    print(f"   Consumer Key: {CONSUMER_KEY[:10]}...")
    print(f"   Access Token: {ACCESS_TOKEN[:10]}...")
except Exception as e:
    print(f"\n❌ Failed to load credentials: {e}")
    sys.exit(1)

# Test 1: Try with tweepy (if available)
print("\n" + "-" * 60)
print("Test 1: Testing with tweepy library")
print("-" * 60)

try:
    import tweepy
    
    auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
    auth.set_access_token(ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    api = tweepy.API(auth)
    
    # Try to verify credentials
    user = api.verify_credentials()
    print(f"✅ SUCCESS! Connected as: @{user.screen_name}")
    print(f"   User ID: {user.id}")
    print(f"   Followers: {user.followers_count}")
    print(f"   API v1.1 still works!")
    
except ImportError:
    print("⚠️  tweepy not installed (pip install tweepy)")
    print("   Trying alternative method...")
    
except tweepy.errors.Unauthorized as e:
    print("❌ UNAUTHORIZED: Invalid or expired credentials")
    print(f"   Error: {e}")
    print("\n   Possible reasons:")
    print("   1. Twitter API v1.1 has been deprecated")
    print("   2. Credentials have been revoked")
    print("   3. App has been deleted from Twitter Developer Portal")
    
except tweepy.errors.Forbidden as e:
    print("❌ FORBIDDEN: Access denied")
    print(f"   Error: {e}")
    print("   Your app may not have the required access level")
    
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}")
    print(f"   {e}")

# Test 2: Try with requests (direct API call)
print("\n" + "-" * 60)
print("Test 2: Testing with direct API call (requests)")
print("-" * 60)

try:
    import requests
    from requests_oauthlib import OAuth1
    
    auth = OAuth1(
        CONSUMER_KEY,
        CONSUMER_SECRET,
        ACCESS_TOKEN,
        ACCESS_TOKEN_SECRET
    )
    
    url = "https://api.twitter.com/1.1/account/verify_credentials.json"
    response = requests.get(url, auth=auth, timeout=10)
    
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ SUCCESS! Connected as: @{data['screen_name']}")
        print(f"   User ID: {data['id']}")
        print(f"   API v1.1 still works!")
        
    elif response.status_code == 401:
        print("❌ UNAUTHORIZED (401): Invalid or expired credentials")
        print(f"   Response: {response.text}")
        print("\n   Twitter API v1.1 is DEPRECATED since 2023")
        print("   You need X API Premium tier ($100+/month)")
        
    elif response.status_code == 403:
        print("❌ FORBIDDEN (403): Access denied")
        print(f"   Response: {response.text}")
        
    else:
        print(f"❌ UNEXPECTED ERROR: {response.status_code}")
        print(f"   Response: {response.text}")
        
except ImportError:
    print("⚠️  requests or requests_oauthlib not installed")
    print("   Install: pip install requests requests-oauthlib")
    
except requests.exceptions.Timeout:
    print("❌ TIMEOUT: Twitter API not responding")
    
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}")
    print(f"   {e}")

# Test 3: Try with peony (the library used in the code)
print("\n" + "-" * 60)
print("Test 3: Testing with peony library (used in twitterasync)")
print("-" * 60)

try:
    import peony
    import asyncio
    
    async def test_peony():
        client = peony.PeonyClient(
            consumer_key=CONSUMER_KEY,
            consumer_secret=CONSUMER_SECRET,
            access_token=ACCESS_TOKEN,
            access_token_secret=ACCESS_TOKEN_SECRET
        )
        
        try:
            user = await client.api.account.verify_credentials.get()
            print(f"✅ SUCCESS! Connected as: @{user.screen_name}")
            print(f"   User ID: {user.id}")
            print(f"   Peony client works!")
            return True
        except Exception as e:
            print(f"❌ FAILED: {type(e).__name__}")
            print(f"   {e}")
            return False
        finally:
            await client.close()
    
    # Run the async test
    result = asyncio.run(test_peony())
    
except ImportError:
    print("⚠️  peony not installed (pip install peony-twitter)")
    
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}")
    print(f"   {e}")

print("\n" + "=" * 60)
print("Summary")
print("=" * 60)
print("\nTwitter API v1.1 Status:")
print("  • Officially DEPRECATED since June 2023")
print("  • Requires X API Premium tier: $100/month minimum")
print("  • Free tier (v2 Essential) has limited endpoints")
print("\nAlternatives:")
print("  1. Upgrade to X API Premium ($100-$5,000/month)")
print("  2. Use Mastodon API (free, open-source)")
print("  3. Use RSS feeds from news sources")
print("  4. Use NewsAPI.org (already working in your system)")
print("\nRecommendation:")
print("  ❌ DISABLE Twitter collection (non-functional + expensive)")
print("  ✅ FOCUS on NewsAPI + RSS feeds (working + free)")
print("=" * 60)
