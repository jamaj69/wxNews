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

# Load credentials from environment
from decouple import config

API_KEY1 = config('NEWS_API_KEY_1')
API_KEY2 = config('NEWS_API_KEY_2')
API_KEY3 = config('NEWS_API_KEY_3')
API_KEY4 = config('NEWS_API_KEY_4')


def url_encode(url):
    return base64.urlsafe_b64encode(zlib.compress(url.encode('utf-8')))[15:31]



def dbCredentials():
    """Return SQLite database path"""
    db_path = config('DB_PATH', default='predator_news.db')
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path



class NewsGather():
    def __init__(self, loop):
        self.sources = dict()
        self.loop = loop
   
        print("Init, Open db...")
        self.url_queue = Queue()   
       
        self.eng = self.dbOpen()
        self.meta = MetaData(self.eng)        
        self.gm_sources = Table('gm_sources', self.meta, autoload=True) 
        self.gm_articles = Table('gm_articles', self.meta, autoload=True) 
        self.sources = self.InitArticles(self.eng, self.meta, self.gm_sources,self.gm_articles)

        print("Init, UpdateNews...")
#        self.loop.call_later(1, self.UpdateNews)
        self.UpdateNews()
    
    def InitArticles(self, eng, meta, gm_sources, gm_articles):
        sources = dict()
        
        con = eng.connect()
        stm = select([gm_sources])
        rs = con.execute(stm) 
        for source in rs.fetchall():
            source_id = source[0]
            print("Source_id:",source_id)
            stm1 = select([gm_articles]).where(gm_articles.c.id_source == source_id)
            articles_qry = con.execute(stm1)
            articles = dict()
            for article in articles_qry.fetchall():
                article_key = article[0]
                print("Article_key",article_key)
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

#        print(sources)
        return sources

    def UpdateNews(self):
#        self.InitQueue()   
        print("Refreshing news...")
        url = "https://newsapi.org/v2/top-headlines?language=en&pageSize=100&apiKey=" + API_KEY1        
        self.url_queue.put(url)      
        url = "https://newsapi.org/v2/top-headlines?language=pt&pageSize=100&apiKey=" + API_KEY2
        self.url_queue.put(url)      
        url = "https://newsapi.org/v2/top-headlines?language=es&pageSize=100&apiKey=" + API_KEY3
        self.url_queue.put(url)      
        url = "https://newsapi.org/v2/top-headlines?language=it&pageSize=100&apiKey=" + API_KEY4
        self.url_queue.put(url)
        self.loop.call_later(600, self.UpdateNews)

    def dbOpen(self):    
        conn = dbCredentials()
        eng = create_engine('postgresql+psycopg2://{user}:{password}@{host}/{dbname}'.format(**conn))
    #    cur = eng.connect()  
    
        meta = MetaData(eng)
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
        gm_sources.create(checkfirst=True)
        
        meta = MetaData(eng)
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
        gm_articles.create(checkfirst=True)
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
        lTrue = True
  
     
        getnewsQueue = self.url_queue                
        print("Refreshing news...")
      
        async with aiohttp.ClientSession() as session:
            while lTrue:
                await asyncio.sleep(0) # cooperate with other tasks
                if not getnewsQueue.empty():
                    url = getnewsQueue.get()
                    print('url:',url)
                    async with session.get(url) as response:
                        response_text = await response.text()
                        JSON_object = json.loads(response_text)
#                        print(JSON_object)
                        articles = JSON_object["articles"]
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
                            if not source_id in self.sources:
                                source_url          = ''
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

                                conn = self.eng.connect()
                                ins = insert(self.gm_sources).values(**new_source)
                                result = conn.execute(ins)
                                
                            
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
                            conn = self.eng.connect()
                            ins = insert(self.gm_articles).values(**new_article)
                            
                            ins_do_nothing = ins.on_conflict_do_nothing(index_elements=['id_article'])

                            result = conn.execute(ins_do_nothing)
                            
                            self.sources[source_id]['articles'][article_key] = new_article
                else:
                    await asyncio.sleep(0) # cooperate with other tasks

        print("Saind da função async_getallnews()")
        return None       

                     
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
