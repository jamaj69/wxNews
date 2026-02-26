#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Dec 26 17:09:16 2020

@author: jamaj
"""

import asyncio
import async_timeout
import feedparser
import aiohttp
import functools

import pprint

INTERVAL = 60


class Task:
    def __init__(self,func,params):
        self.func = func
        self.params = params
        self.status  = 0 
        
    def run(self):
        return asyncio.create_task(self.func(self.params)) 


async def fetch(session, url):
    res = {}
    res['url'] = url
    res['error'] = ""
    res['text'] = ""
    res['stat'] = 0
    with async_timeout.timeout(10):
        try:
            async with session.get(url) as response:
                res['stat']  = response.status
                # print("Headers:  ",response.headers)
                res['text']  = await response.text()            
        except aiohttp.ClientConnectorError as e:
            error = res['error'] = str(e)
            print('Connection Error. url: {url}. error: {error}'.format(**res) )
        except asyncio.TimeoutError as e:
            error = res['error'] = str(e)
            print('Timeout Error. url: {url}. error: {error}'.format(**res) )
        finally:
            return res
        
        
                

async def fetchfeeds(loop, feedurls):
    last_entry = None

    feeds = []
    for url in feedurls:
        feeds.append({'url':url, 'last':""})

    async with aiohttp.ClientSession(loop=loop) as session:
        while True:
            for feed in feeds:
                res = process(session,feed)
                await res
            await asyncio.sleep(INTERVAL)


async def fetchall(feedurls):
    last_entry = None

    feeds = []
    for url in feedurls:
        feeds.append({'url':url, 'last':""})

    async with aiohttp.ClientSession(loop=loop) as session:
        while True:
            tasks = []
            for feed in feeds:
                task = asyncio.create_task(process(session,feed))
                tasks.append(task)
            res = await asyncio.gather(*tasks)
            print('await.sleep...')
            await asyncio.sleep(INTERVAL)


async def process(session,feed):

    url = feed['url']
    resp = await fetch(session,url)

    html = resp['text']
    if html:
        rss = feedparser.parse(html)
        tipo = type(rss['entries'])
        length = len(rss['entries'])            
        rssentries = rss['entries'][0] if type(rss['entries']) is list and len(rss['entries']) > 0 else ""
        print(" url: {url} rss['entries'] {tipo}[{length}]=".format(url=url,tipo = tipo, length = length))
        if feed['last'] and rssentries:
            if feed['last']['title'] != rssentries['title'] and feed['last']['link'] != rssentries['link']:
                print("new entry")
                feed['last'] = rssentries

                print("MSG {}".format(feed['last']['title']))
                print("MSG {}".format(feed['last']['link']))
        else:
            if not rssentries:
                print('rssentries is Empty ...')
            feed['last'] = rssentries


async def main():
    

    feeds = ['http://feeds.bbci.co.uk/news/world/latin_america/rss.xml',
             "http://feeds.bbci.co.uk/news/rss.xml",
             'https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/section/world/rss.xml',
             "https://www.yahoo.com/news/rss/world", 
             "https://www.yahoo.com/news/rss/" ,
             'https://www.buzzfeed.com/world.xml',
             'http://www.aljazeera.com/xml/rss/all.xml',
             'http://defence-blog.com/feed',
             'https://www.e-ir.info/category/blogs/feed/',
             'https://www.globalissues.org/news/feed',
             'https://www.thecipherbrief.com/feed',
             'https://worldnewssuperfast.blogspot.com/feeds/posts/default?alt=rss',
             'http://rss.cnn.com/rss/edition_world.rss',
             'https://www.theguardian.com/world/rss',
             'http://feeds.washingtonpost.com/rss/world',
             'https://www.cnbc.com/id/100727362/device/rss/rss.html',
             'https://timesofindia.indiatimes.com/rssfeeds/296589292.cms',
             'https://www.cnbc.com/id/19746125/device/rss/rss.xml',
             'https://fortune.com/feed',
             'https://www.ft.com/?format=rss',
             'https://www.investing.com/rss/news.rss',
             'https://seekingalpha.com/market_currents.xml',
             'https://economictimes.indiatimes.com/rssfeedsdefault.cms',
             'https://finance.yahoo.com/news/rssindex',
             'https://www.financialexpress.com/feed/',
             'https://www.business-standard.com/rss/home_page_top_stories.rss',
             'https://www.thehindubusinessline.com/?service=rss',
             'https://prod-qt-images.s3.amazonaws.com/production/bloombergquint/feed.xml',
             'https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=1725',
             'https://www.moneyweb.co.za/feed/',
             'https://business.financialpost.com/feed/',
             'https://mjbizdaily.com/feed/',
             'https://www.bmmagazine.co.uk/feed/',
             'https://www.businessdailyafrica.com/latestrss.rss',
             'https://www.canadianbusiness.com/business-news/feed/',
             # 'https://www.businesstravelnews.com/rss/business-travel-news',
             'http://rss.cnn.com/rss/money_topstories.rss',
             'https://businessday.ng/feed/',
             'https://www.biztrailblazer.com/feed',
             'https://www.revyuh.com/feed/',
             'http://businessnews.com.ng/feed/',
             'https://bbj.hu/site/assets/rss/rss.php',
             'http://www.birminghampost.co.uk/business/rss.xml',
             'https://www.businessnews.com.ph/feed/',
             'https://www.thailand-business-news.com/feed',
             'https://www.ibtimes.com.au/rss',
             'http://feeds.feedburner.com/JewishBusinessNews',
             'https://iotbusinessnews.com/feed/',
             'https://www.businessnews.com.au/rssfeed/latest.rss',
             'https://libn.com/feed/',
             'https://www.rt.com/rss/news/',
             'http://feeds.feedburner.com/ndtvnews-world-news',
             'http://www.npr.org/rss/rss.php?id=1004',
             'http://abcnews.go.com/abcnews/internationalheadlines',
             'https://www.spiegel.de/international/index.rss',
             'https://www.cbsnews.com/latest/rss/world',
             'https://sputniknews.com/export/rss2/world/index.xml',
             'http://www.independent.co.uk/news/world/rss',
             'http://www.cbc.ca/cmlink/rss-world',
             'https://www.abc.net.au/news/feed/52278/rss.xml',
             'http://feeds.feedburner.com/time/world',
             'https://time.com/feed',
             'https://www.thesun.co.uk/news/worldnews/feed/',
             'https://www.latimes.com/world/rss2.0.xml',
             'http://www.mirror.co.uk/news/world-news/rss.xml',
             'https://www.euronews.com/rss?level=theme&name=news',
             'https://www.vox.com/rss/world/index.xml',
             'http://feeds.skynews.com/feeds/rss/world.xml',
             'http://feeds.feedburner.com/daily-express-world-news',
             'http://www.smh.com.au/rssheadlines/world/article/rss.xml',
             'https://www.ctvnews.ca/rss/world/ctvnews-ca-world-public-rss-1.822289',
             'https://www.france24.com/en/rss',
             'https://www.scmp.com/rss/91/feed',
             'http://feeds.news24.com/articles/news24/World/rss',
             'https://globalnews.ca/world/feed/',
             'http://www.channelnewsasia.com/rssfeeds/8395884',
             'https://www.rawstory.com/category/world/feed/',
             'https://www.seattletimes.com/nation-world/world/feed/',
             'http://www.thestar.com/content/thestar/feed.RSSManagerServlet.articles.news.world.rss',
             'https://www.brookings.edu/topic/international-affairs/feed/',
             'http://www.washingtontimes.com/rss/headlines/news/world',
             'https://www.todayonline.com/feed/world',
             'https://www.dailytelegraph.com.au/news/world/rss',
             'https://feeds.breakingnews.ie/bnworld',
             'http://www1.cbn.com/cbnnews/world/feed'
             ]
    
    
    task = Task(fetchall,params=None)
    res = await asyncio.gather(task.run())

    
if __name__ == "__main__":  
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())    
