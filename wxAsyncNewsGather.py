#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec  2 16:21:25 2019

@author: jamaj
"""

from __future__ import print_function

import logging
import sys
from multiprocessing import Queue

import urllib.request 
import json
import webbrowser

import asyncio, aiohttp

from asyncio.events import get_event_loop
import time
import base64
import zlib

from sqlalchemy import (create_engine, Table, Column, Integer, 
    String, MetaData, Text)
from sqlalchemy import inspect,select
from sqlalchemy.dialects.sqlite import insert
import os
from urllib.parse import urlparse
import feedparser
from datetime import datetime

# Load credentials from environment
from decouple import config

API_KEY1 = config('NEWS_API_KEY_1')
API_KEY2 = config('NEWS_API_KEY_2')

# RSS Configuration
RSS_TIMEOUT = int(config('RSS_TIMEOUT', default=15))
RSS_MAX_CONCURRENT = int(config('RSS_MAX_CONCURRENT', default=10))
RSS_BATCH_SIZE = int(config('RSS_BATCH_SIZE', default=20))

# MediaStack Configuration
MEDIASTACK_API_KEY = config('MEDIASTACK_API_KEY')
MEDIASTACK_BASE_URL = config('MEDIASTACK_BASE_URL', default='https://api.mediastack.com/v1/news')
MEDIASTACK_RATE_DELAY = 20  # Delay between requests (seconds) - 3 requests/minute


def url_encode(url):
    return base64.urlsafe_b64encode(zlib.compress(url.encode('utf-8')))[15:31]



def dbCredentials():
    """Return SQLite database path"""
    db_path = config('DB_PATH', default='predator_news.db')
    # Make path absolute if relative
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path



class NewsGather():
    def __init__(self, loop):
        self.logger = logging.getLogger(__name__)
        self.sources = dict()
        self.loop = loop
        self.db_lock = asyncio.Lock()  # Lock para serializar inserções SQLite
        self.mediastack_cycle_count = 0  # Counter for MediaStack collection cycles
   
        self.logger.info("Initializing NewsGather...")
        self.logger.debug("Creating URL queue")
        self.url_queue = Queue()   
       
        self.logger.info("Opening database connection")
        self.eng = self.dbOpen()
        self.meta = MetaData()        
        self.gm_sources = Table('gm_sources', self.meta, autoload_with=self.eng) 
        self.gm_articles = Table('gm_articles', self.meta, autoload_with=self.eng) 
        
        self.logger.info("Loading existing articles from database")
        self.sources = self.InitArticles(self.eng, self.meta, self.gm_sources,self.gm_articles)
        self.logger.info(f"Loaded {len(self.sources)} sources from database")

        self.logger.info("Starting news update cycle")
#        self.loop.call_later(1, self.UpdateNews)
        self.UpdateNews()
    
    def InitArticles(self, eng, meta, gm_sources, gm_articles):
        self.logger.debug("InitArticles: Loading sources and articles from database")
        sources = dict()
        
        with eng.connect() as con:
            stm = select(gm_sources)
            rs = con.execute(stm) 
            source_count = 0
            for source in rs.fetchall():
                source_id = source[0]
                source_count += 1
                self.logger.debug(f"Loading source: {source_id}")
                stm1 = select(gm_articles).where(gm_articles.c.id_source == source_id)
                articles_qry = con.execute(stm1)
                articles = dict()
                article_count = 0
                for article in articles_qry.fetchall():
                    article_key = article[0]
                    article_count += 1
                    articles[article_key] = {
                                        'id_article' : article_key ,
                                        'id_source' : article[1] ,
                                        'author' : article[2],
                                        'title' : article[3],
                                        'description' : article[4],
                                        'url' : article[5],
                                        'urlToImage' : article[6],
                                        'publishedAt' : article[7],
                                        'content' : article[8] 
                            }

                sources[source_id] = { 
                        'id_source': source_id,
                        'name': source[1],
                        'description': source[2],
                        'url': source[3],
                        'category': source[4],
                        'language': source[5],
                        'country': source[6],
                        'articles': articles
                     }
                
                if article_count > 0:
                    self.logger.debug(f"  Loaded {article_count} articles for {source_id}")

            self.logger.info(f"InitArticles: Loaded {source_count} sources with articles")
#        print(sources)
        return sources

    def UpdateNews(self):
#        self.InitQueue()   
        self.logger.info("UpdateNews: Queuing news API and RSS requests")
        
        # NewsAPI requests (only EN works on free tier)
        self.logger.debug("Queuing EN request (API_KEY1)")
        url = "https://newsapi.org/v2/top-headlines?language=en&pageSize=100&apiKey=" + API_KEY1        
        self.url_queue.put(url)      
        
        self.logger.debug("Queuing PT request (API_KEY2)")
        url = "https://newsapi.org/v2/top-headlines?language=pt&pageSize=100&apiKey=" + API_KEY2
        self.url_queue.put(url)      
        
        self.logger.debug("Queuing ES request (API_KEY1)")
        url = "https://newsapi.org/v2/top-headlines?language=es&pageSize=100&apiKey=" + API_KEY1
        self.url_queue.put(url)      
        
        self.logger.debug("Queuing IT request (API_KEY2)")
        url = "https://newsapi.org/v2/top-headlines?language=it&pageSize=100&apiKey=" + API_KEY2
        self.url_queue.put(url)
        
        # Schedule RSS collection
        self.logger.debug("Scheduling RSS collection")
        self.loop.create_task(self.collect_rss_feeds())
        
        # Schedule MediaStack collection (every 6 cycles = 1 hour)
        # Free tier: 500 req/month, so ~16 req/day = ~8 collection cycles/day
        self.mediastack_cycle_count += 1
        if self.mediastack_cycle_count >= 6:  # Every 6 cycles (60 minutes)
            self.logger.debug("Scheduling MediaStack collection")
            self.loop.create_task(self.collect_mediastack())
            self.mediastack_cycle_count = 0
        else:
            self.logger.debug(f"Skipping MediaStack collection (cycle {self.mediastack_cycle_count}/6)")
        
        self.logger.info("UpdateNews: Scheduling next update in 600 seconds (10 minutes)")
        self.loop.call_later(600, self.UpdateNews)

    def dbOpen(self):    
        db_path = dbCredentials()
        self.logger.info(f"Opening SQLite database: {db_path}")
        # SQLite connection string with timeout to prevent "database is locked" 
        eng = create_engine(
            f'sqlite:///{db_path}',
            connect_args={'timeout': 30, 'check_same_thread': False},
            pool_pre_ping=True
        )
    #    cur = eng.connect()  
    
        self.logger.debug("Creating metadata and tables if not exist")
        meta = MetaData()
        gm_sources = Table(
            'gm_sources', meta,
             Column('id_source', Text, primary_key=True),
             Column('name', Text),
             Column('description', Text),
             Column('url', Text),
             Column('category', Text),
             Column('language', Text),
             Column('country', Text)
        )
        gm_sources.create(bind=eng, checkfirst=True)
        self.logger.debug("Table gm_sources ready")
        
        meta = MetaData()
        gm_articles = Table(
            'gm_articles', meta,
            Column('id_article', Text, primary_key=True),
            Column('id_source', Text),
            Column('author', Text),
            Column('title', Text),
            Column('description', Text),
            Column('url', Text),
            Column('urlToImage' , Text),
            Column('publishedAt', Text),
            Column('content', Text)
        )
        gm_articles.create(bind=eng, checkfirst=True)
        self.logger.debug("Table gm_articles ready")
        self.logger.info("Database initialization complete")
        return eng
        

    async def track():
        req = client.stream.statuses.filter.post(follow=USERIDS)
        # req is an asynchronous context
        async with req as stream:
            # stream is an asynchronous iterator
            async for tweet in stream:
                # check that you actually receive a tweet
                if events.tweet(tweet):
                    # you can then access items as you would do with a
                    # `PeonyResponse` object
                    user_id = tweet['user']['id_str']
                    username = tweet.user.screen_name   
                    description = tweet['user']['description']
                    location = tweet['user']['location']
                    followers_count = tweet['user']['followers_count']
                    friends_count = tweet['user']['friends_count']
                    listed_count = tweet['user']['listed_count']
                    favourites_count = tweet['user']['favourites_count']
                    statuses_count = tweet['user']['statuses_count']
                    verified = tweet['user']['verified']
                    twitter_id = tweet['id']
                    twitter_ts = tweet['timestamp_ms']
                    
                    #tid_reply = tweet['in_reply_to_status_id_str']
                    #tid_retweet = tweet['retweeted_status']
                    #print('in_reply_to_status_id_str',':',tweet['in_reply_to_status_id_str'])
                    #print('retweeted_status',':',tweet['retweeted_status'])
                    
                    #flds = ['in_reply_to_status_id_str','retweeted_status']
                    #flds = ['in_reply_to_status_id_str']
                    #for key in flds:
                    #    if key in tweet.keys():
                    #        print(key,':',tweet[key])
                    
                    #print(tweet)
                    #for key in tweet.keys():
                    #    print(key,':',tweet[key])
                    hashtags = tweet['entities']['hashtags']
                    user_mentions = tweet['entities']['user_mentions']
                    urls = tweet['entities']['urls']
                    retweeted_status = tweet['retweeted_status'] if 'retweeted_status' in tweet.keys() else ""
                    in_reply_to_status_id_str = tweet['in_reply_to_status_id_str'] if 'in_reply_to_status_id_str' in tweet.keys() else ""

                    
                    #print('hashtags:',hashtags)
                    #print('mentions:',user_mentions)
                    #print('urls:',urls)
                    #print('retweeted_status:',retweeted_status)
                    lRetweet = False
                    lReply = False
           
                    if retweeted_status == None or retweeted_status == "" or retweeted_status == "None":
                        pass
                    else: 
                        #print(type(retweeted_status))
                        print("Retweet:",retweeted_status)
                        twitter_id = retweeted_status['id_str']
                        lRetweet = True

                    in_reply_to_status_id_str = str(in_reply_to_status_id_str)
                    if in_reply_to_status_id_str == None or in_reply_to_status_id_str == "" or in_reply_to_status_id_str == "None":
                        pass
                    else: 
                        #print(type(in_reply_to_status_id_str))
                        print("Reply:",in_reply_to_status_id_str)
                        twitter_id = in_reply_to_status_id_str
                        lReply = True
                        
                    
                    if lRetweet or lReply:
                        print("Retweet or reply")
                        pass
                    else:
                        uid  = create_user(conn, user_id, username)
                        #print(tweet)
                        data = dict(**tweet)
                        data = ToString(data)
                        #print(data)
                        sid =  create_status(conn, uid, tweet.text, data)
                        twt = "uid:{uid} sid:{sid}" 
                        print(twt.format(uid=uid,sid=sid))
                        msg = "{tw_ts} ({tw_id}) | @{username} ({location})({id}): {text}"
                        print(msg.format(tw_id = twitter_id,
                                         tw_ts = twitter_ts,
                                         location = location,
                                         username=username,
                                         id=user_id,
                                         text=tweet.text))
                    
                    #for key in tweet.keys():
                    #    print(key,':',tweet[key])

    async def async_getALLNews(self):
        self.logger.info("async_getALLNews: Starting news collection loop")
        lTrue = True
  
     
        getnewsQueue = self.url_queue                
        self.logger.info(f"Queue size: {getnewsQueue.qsize()} URLs to process")
      
        async with aiohttp.ClientSession() as session:
            while lTrue:
                await asyncio.sleep(0) # cooperate with other tasks
                if not getnewsQueue.empty():
                    url = getnewsQueue.get()
                    # Extract language from URL for logging
                    lang = 'unknown'
                    if 'language=en' in url:
                        lang = 'EN'
                    elif 'language=pt' in url:
                        lang = 'PT'
                    elif 'language=es' in url:
                        lang = 'ES'
                    elif 'language=it' in url:
                        lang = 'IT'
                    self.logger.info(f"Fetching news for language: {lang}")
                    self.logger.debug(f"URL: {url[:80]}...")
                    try:
                        async with session.get(url) as response:
                            if response.status != 200:
                                self.logger.warning(f"HTTP {response.status} for {lang}")
                                continue
                            
                            self.logger.debug(f"Response received for {lang}, parsing JSON")
                            response_text = await response.text()
                            JSON_object = json.loads(response_text)
                            
                            if JSON_object.get('status') != 'ok':
                                self.logger.error(f"API error for {lang}: {JSON_object.get('message')}")
                                continue
                            
#                        print(JSON_object)
                        articles = JSON_object["articles"]
                        self.logger.info(f"Processing {len(articles)} articles for {lang}")
                        
                        articles_inserted = 0
                        articles_skipped = 0
                        sources_added = 0
                        
                        for article in articles:
                            await asyncio.sleep(0) # cooperate with other tasks
                            article_source = article['source']
                            article_source_id = article_source['id']
                            article_source_name = article_source['name']
                            source_id           = article_source_name if article_source_id is None else article_source_id
                            source_name         = article_source_name
                            article_author = article['author']
                            article_title = article['title']
                            article_description = article['description']
                            article_url = article['url']
                            article_urlToImage = article['urlToImage']
                            article_publishedAt = article['publishedAt']
                            article_content = article['content']
#                            print('article_source_id',source_id)
#                            print('article_source_name',source_name)
#                            print('article_author',article_author)
#                            print('article_title',article_title)
#                            print('article_description',article_description)
#                            print('article_url',article_url)
#                            print('article_urlToImage',article_urlToImage)
#                            print('article_publishedAt',article_publishedAt)
#                            print('article_content',article_content)
                            article_key = url_encode(article_title+article_url+article_publishedAt)
                            
                            # Try to extract source URL from article URL
                            if not article_url:
                                article_url = ''
                            try:
                                parsed_url = urlparse(article_url)
                                inferred_source_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                            except:
                                inferred_source_url = ''
                            
                            if not source_id in self.sources:
                                self.logger.debug(f"New source detected: {source_name} (id: {source_id})")
                                source_url          = inferred_source_url
                                source_description  = ''
                                source_articles = dict()
                                
                                new_source = { 
                                        'id_source' : source_id ,
                                        'name' : source_name, 
                                        'url': source_url, 
                                        'description': source_description, 
                                        'articles': source_articles, 
                                        'category' : '', 
                                        'country': '', 
                                        'language': '' 
                                        }                             
                                
                                self.sources[source_id] = new_source
                                new_source = { 
                                        'id_source' : source_id ,
                                        'name' : source_name, 
                                        'url': source_url, 
                                        'description': source_description, 
                                        'category' : '', 
                                        'country': '', 
                                        'language': '' 
                                    }                             

                                self.logger.debug(f"Inserting new source: {source_name}")
                                # Use lock e context manager para evitar "database is locked"
                                async with self.db_lock:
                                    with self.eng.connect() as conn:
                                        try:
                                            ins = insert(self.gm_sources).values(**new_source)
                                            result = conn.execute(ins)
                                            conn.commit()
                                            sources_added += 1
                                            self.logger.info(f"✅ Added source: {source_name}")
                                            
                                            # Try to discover RSS feed for this new source
                                            if source_url:
                                                self.logger.debug(f"Attempting to discover RSS for {source_name}...")
                                                self.loop.create_task(
                                                    self.register_rss_source(session, source_id, source_name, source_url)
                                                )
                                        except Exception as e:
                                            self.logger.error(f"Failed to insert source {source_name}: {e}")
                                            conn.rollback()
                                
                            
                            new_article = {
                                                'id_article' : article_key ,
                                                'id_source' : source_id ,
                                                'author' : article_author,
                                                'title' : article_title,
                                                'description' : article_description,
                                                'url' : article_url,
                                                'urlToImage' : article_urlToImage,
                                                'publishedAt' : article_publishedAt,
                                                'content' : article_content 
                                            }
                            
                            self.logger.debug(f"Inserting article: {article_title[:50]}...")
                            # Use lock e context manager para evitar "database is locked"
                            async with self.db_lock:
                                with self.eng.connect() as conn:
                                    try:
                                        ins = insert(self.gm_articles).values(**new_article)
                                        # Ignore conflicts on both id_article and url (both have UNIQUE constraints)
                                        ins_do_nothing = ins.on_conflict_do_nothing()
                                        result = conn.execute(ins_do_nothing)
                                        conn.commit()
                                        
                                        if result.rowcount > 0:
                                            articles_inserted += 1
                                            self.logger.info(f"✅ [{source_name}] {article_title[:60]}...")
                                        else:
                                            articles_skipped += 1
                                            self.logger.debug(f"⏭️  [{source_name}] Already exists: {article_title[:40]}...")
                                        
                                        self.sources[source_id]['articles'][article_key] = new_article
                                    except Exception as e:
                                        self.logger.error(f"Failed to insert article '{article_title[:40]}...': {e}")
                                        conn.rollback()
                        self.logger.info(f"Summary for {lang}: {articles_inserted} inserted, {articles_skipped} skipped, {sources_added} new sources")
                        
                    except aiohttp.ClientError as e:
                        self.logger.error(f"Network error fetching {lang}: {e}")
                    except json.JSONDecodeError as e:
                        self.logger.error(f"JSON decode error for {lang}: {e}")
                    except Exception as e:
                        self.logger.error(f"Unexpected error processing {lang}: {e}", exc_info=True)
                else:
                    await asyncio.sleep(0) # cooperate with other tasks

        self.logger.info("async_getALLNews: Exiting news collection loop")
        return None       

    async def discover_rss_feed(self, session, domain, source_name):
        """
        Try to discover RSS feed for a domain.
        Tests common RSS URL patterns.
        """
        common_patterns = [
            f'https://{domain}/feed/',
            f'https://{domain}/rss',
            f'https://{domain}/rss.xml',
            f'https://{domain}/feed',
            f'https://{domain}/feeds/posts/default',  # Blogger
            f'https://{domain}/index.xml',
            f'https://{domain}/atom.xml',
            f'http://{domain}/feed/',
            f'http://{domain}/rss',
        ]
        
        for rss_url in common_patterns:
            try:
                async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        content = await response.text()
                        # Verify it's actually an RSS/Atom feed
                        if any(tag in content[:1000] for tag in ['<rss', '<feed', '<channel']):
                            self.logger.info(f"📡 Discovered RSS for {source_name}: {rss_url}")
                            return rss_url
            except:
                continue
        
        return None
    
    async def register_rss_source(self, session, source_id, source_name, source_url):
        """
        Check if source has RSS feed and register it if found.
        """
        # Check if already registered as RSS
        rss_id = f'rss-{source_id}'
        if rss_id in self.sources:
            return  # Already registered
        
        try:
            # Extract domain from source URL
            if not source_url or source_url.strip() == '':
                return
            
            parsed = urlparse(source_url)
            domain = parsed.netloc or parsed.path
            if not domain:
                return
            
            # Try to discover RSS feed
            rss_url = await self.discover_rss_feed(session, domain, source_name)
            if rss_url:
                # Register as new RSS source
                new_rss_source = {
                    'id_source': rss_id,
                    'name': source_name,
                    'url': rss_url,
                    'description': f'Auto-discovered from NewsAPI',
                    'category': 'general',
                    'language': 'en',
                    'country': ''
                }
                
                async with self.db_lock:
                    with self.eng.connect() as conn:
                        try:
                            ins = insert(self.gm_sources).values(**new_rss_source)
                            ins = ins.on_conflict_do_nothing()
                            result = conn.execute(ins)
                            conn.commit()
                            if result.rowcount > 0:
                                self.sources[rss_id] = {**new_rss_source, 'articles': {}}
                                self.logger.info(f"✅ Registered RSS source: {source_name} -> {rss_url}")
                        except Exception as e:
                            self.logger.error(f"Failed to register RSS source {source_name}: {e}")
                            conn.rollback()
        except Exception as e:
            self.logger.debug(f"Could not discover RSS for {source_name}: {e}")
    
    async def collect_rss_feeds(self):
        """
        Collect articles from all RSS sources in database.
        """
        self.logger.info("Starting RSS collection...")        
        
        # Get all RSS sources from database
        rss_sources = []
        with self.eng.connect() as conn:
            stmt = select(self.gm_sources).where(
                self.gm_sources.c.id_source.like('rss-%')
            )
            results = conn.execute(stmt).fetchall()
            for row in results:
                rss_sources.append({
                    'id': row[0],
                    'name': row[1],
                    'url': row[3],
                    'language': row[5] or 'en'
                })
        
        if not rss_sources:
            self.logger.info("No RSS sources found in database")
            return
        
        self.logger.info(f"Found {len(rss_sources)} RSS sources to process")
        
        # Process feeds with semaphore for concurrency control
        semaphore = asyncio.Semaphore(RSS_MAX_CONCURRENT)
        
        async with aiohttp.ClientSession() as session:
            # Process in batches
            for i in range(0, len(rss_sources), RSS_BATCH_SIZE):
                batch = rss_sources[i:i+RSS_BATCH_SIZE]
                self.logger.info(f"Processing RSS batch {i//RSS_BATCH_SIZE + 1} ({len(batch)} feeds)...")
                
                tasks = [
                    self.process_rss_feed_with_semaphore(session, source, semaphore)
                    for source in batch
                ]
                await asyncio.gather(*tasks, return_exceptions=True)
        
        self.logger.info("RSS collection complete")
    
    async def process_rss_feed_with_semaphore(self, session, source, semaphore):
        """
        Process RSS feed with semaphore control.
        """
        async with semaphore:
            return await self.process_rss_feed(session, source)
    
    async def process_rss_feed(self, session, source):
        """
        Fetch and process a single RSS feed.
        """
        source_id = source['id']
        source_name = source['name']
        rss_url = source['url']
        
        try:
            async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=RSS_TIMEOUT)) as response:
                if response.status != 200:
                    self.logger.warning(f"❌ [{source_name}] HTTP {response.status}")
                    return
                
                content = await response.text()
                feed = feedparser.parse(content)
                
                if not feed.entries:
                    self.logger.debug(f"⚠️  [{source_name}] No entries found")
                    return
                
                self.logger.debug(f"📥 [{source_name}] Received {len(feed.entries)} entries")
                
                articles_inserted = 0
                articles_skipped = 0
                
                for entry in feed.entries:
                    # Extract article data
                    title = entry.get('title', '')
                    url = entry.get('link', '')
                    description = entry.get('summary', entry.get('description', ''))
                    author = entry.get('author', '')
                    published = entry.get('published', entry.get('updated', ''))
                    
                    if not title or not url:
                        continue
                    
                    # Generate article key
                    article_key = url_encode(title + url + published)
                    
                    # Create article object
                    new_article = {
                        'id_article': article_key,
                        'id_source': source_id,
                        'author': author,
                        'title': title,
                        'description': description[:500] if description else '',
                        'url': url,
                        'urlToImage': '',
                        'publishedAt': published,
                        'content': ''
                    }
                    
                    # Insert article
                    async with self.db_lock:
                        with self.eng.connect() as conn:
                            try:
                                ins = insert(self.gm_articles).values(**new_article)
                                ins_do_nothing = ins.on_conflict_do_nothing()
                                result = conn.execute(ins_do_nothing)
                                conn.commit()
                                
                                if result.rowcount > 0:
                                    articles_inserted += 1
                                    if articles_inserted <= 5:  # Log first 5
                                        self.logger.info(f"  ✅ [{source_name}] {title[:60]}...")
                                else:
                                    articles_skipped += 1
                            except Exception as e:
                                self.logger.error(f"Failed to insert RSS article: {e}")
                                conn.rollback()
                
                if articles_inserted > 0:
                    self.logger.info(f"✅ [{source_name}] {articles_inserted} new, {articles_skipped} existing")
                else:
                    self.logger.debug(f"⏭️  [{source_name}] All {articles_skipped} articles already exist")
                    
        except asyncio.TimeoutError:
            self.logger.warning(f"⏱️  [{source_name}] Timeout after {RSS_TIMEOUT}s")
        except Exception as e:
            self.logger.error(f"❌ [{source_name}] Error: {str(e)[:100]}")
    
    async def collect_mediastack(self):
        """
        Collect articles from MediaStack API with rate limiting.
        Free tier: 500 requests/month, ~3-4 requests/minute
        Strategy: Collect PT, ES, IT (EN covered by NewsAPI)
        """
        self.logger.info("Starting MediaStack collection...")
        
        # Languages to collect (EN already covered by NewsAPI)
        languages = ['pt', 'es', 'it']
        
        stats = {
            'total_fetched': 0,
            'inserted': 0,
            'skipped': 0,
            'errors': 0
        }
        
        async with aiohttp.ClientSession() as session:
            for i, language in enumerate(languages):
                self.logger.info(f"🌍 Collecting MediaStack news for language: {language}")
                
                try:
                    # Prepare request
                    params = {
                        'access_key': MEDIASTACK_API_KEY,
                        'languages': language,
                        'limit': 25,  # Collect 25 articles per language
                        'sort': 'published_desc'
                    }
                    
                    # Fetch news
                    async with session.get(
                        MEDIASTACK_BASE_URL, 
                        params=params, 
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            
                            # Check for API errors
                            if 'error' in data:
                                error_info = data['error']
                                self.logger.error(
                                    f"❌ MediaStack API Error: {error_info.get('code')} - "
                                    f"{error_info.get('message')}"
                                )
                                continue
                            
                            articles = data.get('data', [])
                            total = data.get('pagination', {}).get('total', 0)
                            stats['total_fetched'] += len(articles)
                            
                            self.logger.info(
                                f"📥 MediaStack [{language}]: Received {len(articles)}/{total} articles"
                            )
                            
                            # Process and store articles
                            for article_data in articles:
                                result = await self.process_mediastack_article(article_data, language, session)
                                if result == 'inserted':
                                    stats['inserted'] += 1
                                elif result == 'skipped':
                                    stats['skipped'] += 1
                                else:
                                    stats['errors'] += 1
                        
                        elif response.status == 429:
                            self.logger.error(f"❌ MediaStack: Rate limit exceeded (429)")
                            break  # Stop processing
                        elif response.status == 401:
                            self.logger.error(f"❌ MediaStack: Invalid API key (401)")
                            break
                        else:
                            error_text = await response.text()
                            self.logger.error(f"❌ MediaStack: HTTP {response.status} - {error_text[:200]}")
                
                except asyncio.TimeoutError:
                    self.logger.error(f"⏱️  MediaStack [{language}]: Timeout")
                    stats['errors'] += 1
                except Exception as e:
                    self.logger.error(f"❌ MediaStack [{language}]: Error - {str(e)}")
                    stats['errors'] += 1
                
                # Rate limiting: Wait before next request (except after last one)
                if i < len(languages) - 1:
                    self.logger.debug(f"⏳ Waiting {MEDIASTACK_RATE_DELAY}s for rate limiting...")
                    await asyncio.sleep(MEDIASTACK_RATE_DELAY)
        
        # Log statistics
        self.logger.info(
            f"✅ MediaStack collection complete: "
            f"{stats['inserted']} inserted, {stats['skipped']} skipped, {stats['errors']} errors "
            f"(fetched {stats['total_fetched']} total)"
        )
    
    async def process_mediastack_article(self, article_data, language, session):
        """
        Process and store a single MediaStack article.
        Returns: 'inserted', 'skipped', or 'error'
        """
        try:
            # Extract data with None handling
            title = article_data.get('title') or ''
            url = article_data.get('url') or ''
            description = article_data.get('description') or ''
            author = article_data.get('author') or ''
            source_name = article_data.get('source') or 'unknown'
            category = article_data.get('category') or 'general'
            published_at = article_data.get('published_at') or ''
            image = article_data.get('image') or ''
            
            # Strip whitespace only if not empty
            title = title.strip() if title else ''
            url = url.strip() if url else ''
            description = description.strip() if description else ''
            author = author.strip() if author else ''
            source_name = source_name.strip() if source_name else 'unknown'
            category = category.strip() if category else 'general'
            
            # Validate required fields
            if not title or not url:
                return 'error'
            
            # Extract source URL from article URL
            source_url = ''
            try:
                parsed_url = urlparse(url)
                source_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            except:
                source_url = ''
            
            # Parse date
            try:
                if published_at:
                    pub_date = datetime.fromisoformat(published_at.replace('+00:00', ''))
                else:
                    pub_date = datetime.utcnow()
            except ValueError:
                pub_date = datetime.utcnow()
            
            # Create source ID (mediastack-source_name)
            source_id = f"mediastack-{source_name.lower().replace(' ', '-').replace('_', '-')}"
            
            # Create article ID using url_encode function
            article_id = url_encode(title + url + published_at)
            
            # Ensure source exists
            is_new_source = await self.ensure_mediastack_source_exists(
                source_id, source_name, language, category, source_url
            )
            
            # Try to discover RSS feed for new sources
            if is_new_source and source_url:
                self.logger.debug(f"Attempting to discover RSS for MediaStack source: {source_name}...")
                self.loop.create_task(
                    self.register_rss_source(session, source_id, source_name, source_url)
                )
            
            # Create article object
            new_article = {
                'id_article': article_id,
                'id_source': source_id,
                'author': author[:200] if author else '',
                'title': title[:500] if title else '',
                'description': description[:1000] if description else '',
                'url': url[:500] if url else '',
                'urlToImage': image[:500] if image else '',
                'publishedAt': pub_date.isoformat(),
                'content': ''
            }
            
            # Insert article with lock
            async with self.db_lock:
                with self.eng.connect() as conn:
                    try:
                        ins = insert(self.gm_articles).values(**new_article)
                        ins_do_nothing = ins.on_conflict_do_nothing()
                        result = conn.execute(ins_do_nothing)
                        conn.commit()
                        
                        if result.rowcount > 0:
                            self.logger.debug(f"  ✅ MediaStack: {title[:60]}...")
                            return 'inserted'
                        else:
                            return 'skipped'
                    except Exception as e:
                        self.logger.error(f"Failed to insert MediaStack article: {e}")
                        conn.rollback()
                        return 'error'
        
        except Exception as e:
            self.logger.error(f"Error processing MediaStack article: {str(e)}")
            return 'error'
    
    async def ensure_mediastack_source_exists(self, source_id, source_name, language, category, source_url=''):
        """
        Ensure MediaStack source exists in database.
        Returns: True if source was newly created, False if it already existed
        """
        async with self.db_lock:
            with self.eng.connect() as conn:
                try:
                    # Check if source exists
                    stmt = select(self.gm_sources.c.id_source).where(
                        self.gm_sources.c.id_source == source_id
                    )
                    result = conn.execute(stmt).fetchone()
                    
                    if not result:
                        # Insert new source
                        ins = insert(self.gm_sources).values(
                            id_source=source_id,
                            name=source_name,
                            description='MediaStack news source',
                            url=source_url,  # Now capturing actual source URL
                            category=category,
                            language=language,
                            country=''
                        )
                        ins = ins.on_conflict_do_nothing(index_elements=['id_source'])
                        conn.execute(ins)
                        conn.commit()
                        self.logger.info(f"✅ Created MediaStack source: {source_name} ({source_url})")
                        return True
                    return False
                except Exception as e:
                    self.logger.error(f"Error ensuring MediaStack source exists: {e}")
                    conn.rollback()
                    return False
                     
    def getNewsSources(self):
#        url = "https://newsapi.org/v2/sources?country=br&apiKey=" + API_KEY
        url = "https://newsapi.org/v2/sources?language=en&apiKey=" + API_KEY1
        print('getNewsSource url:',url)
        sources = []

        with urllib.request.urlopen(url) as response:
            response_text = response.read()   
            encoding = response.info().get_content_charset('utf-8')
            JSON_object = json.loads(response_text.decode(encoding))                        
            #return JSON_object            
            for source in JSON_object["sources"]:
                print(source)
                source_key          = source['id']
                source_name         = source['name']
                source_url          = source['url']
                source_description  = source['description']
                source['articles'] = dict()
#                self.sources_list.InsertItem(0, source_name)
                sources.append(source)
        return sources


if __name__ == '__main__':
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)   # register the App instance with Twisted:


     # start the event loop:
    loop = asyncio.get_event_loop()
    app = NewsGather(loop)
    loop.run_until_complete(app.async_getALLNews())
