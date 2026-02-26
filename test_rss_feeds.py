#!/usr/bin/env python3
"""
RSS Feed Validator
Tests all RSS feeds in rssfeeds.conf to identify working/broken feeds

Usage:
    python3 test_rss_feeds.py
"""

import json
import asyncio
import aiohttp
import feedparser
import time
from datetime import datetime
from urllib.parse import urlparse


class RSSFeedTester:
    def __init__(self, timeout=15):
        self.timeout = timeout
        self.results = {
            'working': [],
            'broken': [],
            'timeout': [],
            'invalid_xml': [],
            'total': 0,
            'start_time': None,
            'end_time': None
        }
    
    async def test_feed(self, session, feed_data):
        """Test a single RSS feed"""
        url = feed_data['url']
        result = {
            'url': url,
            'status': None,
            'error': None,
            'entries_count': 0,
            'title': None,
            'response_time': None
        }
        
        start = time.time()
        
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.timeout)) as response:
                response_time = time.time() - start
                result['status'] = response.status
                result['response_time'] = round(response_time, 2)
                
                if response.status == 200:
                    content = await response.text()
                    
                    # Parse RSS/Atom feed
                    parsed = feedparser.parse(content)
                    
                    # Check if it's a valid feed
                    if hasattr(parsed, 'bozo_exception'):
                        result['error'] = str(parsed.bozo_exception)
                        result['category'] = 'invalid_xml'
                    elif len(parsed.entries) == 0:
                        result['error'] = 'No entries found'
                        result['category'] = 'invalid_xml'
                    else:
                        result['entries_count'] = len(parsed.entries)
                        result['title'] = parsed.feed.get('title', 'Unknown')
                        result['category'] = 'working'
                else:
                    result['error'] = f'HTTP {response.status}'
                    result['category'] = 'broken'
                    
        except asyncio.TimeoutError:
            result['error'] = 'Timeout'
            result['category'] = 'timeout'
            result['response_time'] = self.timeout
            
        except aiohttp.ClientConnectorError as e:
            result['error'] = f'Connection error: {str(e)[:100]}'
            result['category'] = 'broken'
            
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {str(e)[:100]}'
            result['category'] = 'broken'
        
        return result
    
    async def test_all_feeds(self, feeds):
        """Test all feeds concurrently"""
        print(f"🔍 Testing {len(feeds)} RSS feeds...")
        print(f"⏱️  Timeout: {self.timeout}s per feed")
        print("=" * 80)
        
        self.results['total'] = len(feeds)
        self.results['start_time'] = datetime.now().isoformat()
        
        # Create session with custom headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; RSSFeedTester/1.0)'
        }
        
        async with aiohttp.ClientSession(headers=headers) as session:
            # Test feeds in batches to avoid overwhelming the system
            batch_size = 10
            all_results = []
            
            for i in range(0, len(feeds), batch_size):
                batch = feeds[i:i+batch_size]
                print(f"Testing batch {i//batch_size + 1}/{(len(feeds)-1)//batch_size + 1}...", end=' ')
                
                tasks = [self.test_feed(session, feed) for feed in batch]
                batch_results = await asyncio.gather(*tasks)
                all_results.extend(batch_results)
                
                # Print progress
                working = sum(1 for r in all_results if r.get('category') == 'working')
                print(f"({working}/{len(all_results)} working so far)")
                
                # Small delay between batches
                await asyncio.sleep(0.5)
        
        # Categorize results
        for result in all_results:
            category = result.get('category', 'broken')
            self.results[category].append(result)
        
        self.results['end_time'] = datetime.now().isoformat()
        
        return all_results
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 80)
        print("📊 TEST SUMMARY")
        print("=" * 80)
        
        total = self.results['total']
        working = len(self.results['working'])
        broken = len(self.results['broken'])
        timeout = len(self.results['timeout'])
        invalid = len(self.results['invalid_xml'])
        
        print(f"\n✅ Working:        {working:3d} / {total} ({working*100//total}%)")
        print(f"❌ Broken:         {broken:3d} / {total} ({broken*100//total}%)")
        print(f"⏱️  Timeout:        {timeout:3d} / {total} ({timeout*100//total}%)")
        print(f"⚠️  Invalid XML:    {invalid:3d} / {total} ({invalid*100//total}%)")
        
        # Top working feeds
        if self.results['working']:
            print("\n" + "=" * 80)
            print("✅ WORKING FEEDS (Sample - 20 fastest)")
            print("=" * 80)
            
            sorted_working = sorted(self.results['working'], 
                                   key=lambda x: x['response_time'])[:20]
            
            for feed in sorted_working:
                domain = urlparse(feed['url']).netloc
                print(f"  {feed['entries_count']:3d} entries | "
                      f"{feed['response_time']:5.2f}s | "
                      f"{domain:40s}")
        
        # Broken feeds by error type
        if self.results['broken'] or self.results['timeout'] or self.results['invalid_xml']:
            print("\n" + "=" * 80)
            print("❌ BROKEN/PROBLEMATIC FEEDS")
            print("=" * 80)
            
            # Group by error type
            errors = {}
            for feed in (self.results['broken'] + self.results['timeout'] + 
                        self.results['invalid_xml']):
                error = feed.get('error', 'Unknown error')
                # Simplify error message
                if 'HTTP' in error:
                    error_key = error.split(':')[0]
                elif 'Timeout' in error:
                    error_key = 'Timeout'
                elif 'Connection' in error:
                    error_key = 'Connection error'
                elif 'SSL' in error or 'Certificate' in error:
                    error_key = 'SSL/Certificate error'
                else:
                    error_key = error[:50]
                
                if error_key not in errors:
                    errors[error_key] = []
                errors[error_key].append(feed)
            
            for error_type, feeds in sorted(errors.items(), 
                                           key=lambda x: len(x[1]), 
                                           reverse=True):
                print(f"\n  {error_type} ({len(feeds)} feeds):")
                for feed in feeds[:5]:  # Show up to 5 examples
                    domain = urlparse(feed['url']).netloc
                    print(f"    - {domain}")
                if len(feeds) > 5:
                    print(f"    ... and {len(feeds)-5} more")
    
    def save_results(self, filename='rss_feed_test_results.json'):
        """Save detailed results to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Detailed results saved to: {filename}")
    
    def save_working_feeds(self, original_feeds, filename='rssfeeds_working.conf'):
        """Save only working feeds to a new config file"""
        working_urls = {feed['url'] for feed in self.results['working']}
        working_feeds = [feed for feed in original_feeds if feed['url'] in working_urls]
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(working_feeds, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Working feeds saved to: {filename}")
        print(f"   ({len(working_feeds)} working feeds)")


async def main():
    """Main function"""
    print("=" * 80)
    print("RSS FEED VALIDATOR")
    print("=" * 80)
    
    # Load RSS feeds
    try:
        with open('rssfeeds.conf', 'r') as f:
            feeds = json.load(f)
    except FileNotFoundError:
        print("❌ Error: rssfeeds.conf not found")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing rssfeeds.conf: {e}")
        return
    
    # Create tester and run tests
    tester = RSSFeedTester(timeout=15)
    
    start_time = time.time()
    await tester.test_all_feeds(feeds)
    elapsed = time.time() - start_time
    
    # Print results
    tester.print_summary()
    
    print(f"\n⏱️  Total time: {elapsed:.1f}s")
    print("=" * 80)
    
    # Save results
    tester.save_results()
    tester.save_working_feeds(feeds)
    
    print("\n✅ Testing complete!")


if __name__ == '__main__':
    asyncio.run(main())
