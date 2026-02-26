#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 30 19:29:07 2020

@author: jamaj
"""
import datetime
import time
import sys
from blist import blist,sortedlist
import asyncio
import async_timeout
import feedparser
import aiohttp
import functools
import pprint
import json
import Scheduler

INTERVAL = 60


# async def fetch(session, url):
#     res = {}
#     res['url'] = url
#     res['error'] = ""
#     res['text'] = ""
#     res['stat'] = 0
#     with async_timeout.timeout(60):
#        try:
#            async with session.get(url) as response:
#                res['stat']  = response.status
#                # print("Headers:  ",response.headers)
#                res['text']  = await response.text()            
#        except aiohttp.ClientConnectorError as e:
#            error= 'Connection Error. url: {url}. error: {error}'.format(url=url,error=str(e))
#            res['error']  = error            
#        except asyncio.TimeoutError as e:
#            error= 'Timeout Error. url: {url}. error: {error}'.format(url=url,error=str(e))
#            res['error']  = error            
#        except Exception as e:
#            error = 'Error. url: {url}. error: {error}'.format(url=url,error=e.__class__)
#            res['error']  = error            
#        finally:
#            return res
            
# async def fetchall(feedurls,control):
#     last_entry = None

#     feeds = []
#     for url in feedurls:
#         feeds.append({'url':url, 'last':""})

#     async with aiohttp.ClientSession() as session:
#         while True:
#             tasks = []
#             for feed in feeds:
#                 task = asyncio.create_task(process(session,feed))
#                 tasks.append(task)
#             res = await asyncio.gather(*tasks)
#             print('await.sleep...')
#             await asyncio.sleep(INTERVAL)


async def fetch_news(params=None,control=None, news=None):
    last_entry = None
    feeds = params['feeds']
    session = params['session']
    TIMEOUT = params['TIMEOUT']
    # news = params['news']

    print('Entrando em fetch_news')

    while True:
        tasks = []
        for feed in feeds:
            # print('feed',feed)
            params = { 'news': news, 'session': session, 'feed': feed, 'control':control , 'TIMEOUT': TIMEOUT}
            task = control.add_task(func=process,params=params)
            # print('create process')
            tasks.append(task)
            await asyncio.sleep(0)
        task_group = [ task.run() for task in tasks ]
        # res = await control.runtasks(tasks)
        # print('fetchall tasks:',task_group)
        ress = await control.runtasks(tasks)
        
        for res in ress:
            if res:
                # print('yielding url={url},last={last}, rss len() = {leng}'.format(url=res['url'],last=res['last'], leng=len(res['rss'])))
                yield res
            # print('Resultado >', res )
            await asyncio.sleep(0)
            
        print('await.sleep...')
        print('Classificando o dicionário global "news", que tem agora {num}'.format(num=len(news.keys())))
        # news = dict(sorted(news.items(), key=lambda item: item[1]['timestamp']))        
        # control.return_finish(result=feeds)
        # reschedule
        # control.return_reschedule(NTERVAL,result=feedurls)
        await asyncio.sleep(INTERVAL)

async def process(params=None,control=None):
    # print('params', params)
    feed = params['feed']
    session = params['session']
    TIMEOUT =  params['TIMEOUT']
    
    url  = feed['url']
    last = feed['last']
    
    rss_list  = feed['rss'] 
    
    news = params['news']
    
    resp = await Scheduler.fetch(session,url,TIMEOUT)
    
    if resp['error']:
        print("erro url: {url}".format(url=url))
        feed['error'] = resp['error'] 
    
    print("process({url})".format(url=url))
    html = resp['text']
    if html:
        rss = feedparser.parse(html)
        tipo = type(rss['entries'])
        length = len(rss['entries'])            
        rssentries = rss['entries'] if type(rss['entries']) is list and len(rss['entries']) > 0 else ""
        print(" url: {url} rss['entries'] {tipo}[{length}]=".format(url=url,tipo = tipo, length = length))

        if rssentries:  
            # lastrss = rssentries[0]
            if feed['last']:
                lasttime = feed['last']['timestamp']
            else:
                lasttime = ""
                
            id_rss = ""
            async def rss_generator(rssentries,lasttime):                
  
                for lastrss in reversed(rssentries):
                    if 'published_parsed' in lastrss.keys() and lastrss['published_parsed']:
                        # dt = time.strftime('%Y-%m-%dT%H:%M:%SZ', lastrss['published_parsed'])
                        dt = Scheduler.Norm_DateTime(lastrss['published'])
                        lastrss['timestamp'] = dt
                    elif 'updated_parsed' in lastrss.keys() and lastrss['updated_parsed']:
                        # dt = time.strftime('%Y-%m-%dT%H:%M:%SZ', lastrss['updated_parsed'])
                        dt = Scheduler.Norm_DateTime(lastrss['updated'])
                        lastrss['timestamp'] = dt
                    else:
                        dt = ""
                
                    if dt >  lasttime:
                        newrss = lastrss                        
                        if 'id' in newrss and newrss['id']:
                            id_rss = Scheduler.GetShortURL(newrss['link'] )
                        else:
                            if 'link' in newrss:
                                id_rss = Scheduler.GetShortURL(newrss['link'] )
                            else:
                                id_rss = Scheduler.GetShortURL( url )
                                
                        print('id_rss: {id_rss}'.format(id_rss=id_rss)) 
                        newrss['id'] = id_rss
        
                        # pprint.pprint(newrss)
                        # rss_list.append(newrss)
                        if not id_rss in news:
                            feed['last'] = lastrss                
                            # print("New entry > yield")
                            yield lastrss
                    await asyncio.sleep(0)
            
            
            async for newrss in rss_generator(rssentries,lasttime):
                id_rss = newrss['id']
        
                # newrss['translated'] = await Scheduler.Translate(newrss['title'])
                if id_rss in news:
                    print('{id} já inserido em news'.format(id=id_rss))
                else:
                    print('Inserindo {id} em news'.format(id=id_rss))
                    newrss['translated'] = newrss['title']
                    # newrss['translated'] = await Scheduler.Translate(newrss['title'],session=session)
                    news[id_rss] = newrss
                    rss_list[id_rss] = newrss
                    print('news tem agora {tam} notícias'.format(tam=len(news.keys())))

                await asyncio.sleep(0)

            # print('last feed fetched:', feed )
                
        else:
            print('rssentries is Empty ...')

        await asyncio.sleep(0)

        feed['rss'] = rss_list
        # pprint.pprint(rss_list)
        url  = feed['url']
        last = feed['last']


    return feed          


async def run(params,control):
    
    print('Entrando em rss_rask.run')

    # feedurls = ['http://feeds.bbci.co.uk/news/world/latin_america/rss.xml',
    #          "http://feeds.bbci.co.uk/news/rss.xml",
    #          'https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/section/world/rss.xml',
    #          "https://www.yahoo.com/news/rss/world",
    #          'https://br.noticias.yahoo.com/rss',
    #          'https://au.news.yahoo.com/rss',
    #          'https://uk.news.yahoo.com/rss',
    #          'https://it.notizie.yahoo.com/rss',
    #          "https://www.yahoo.com/news/rss/" ,
    #          'https://www.buzzfeed.com/world.xml',
    #          'http://www.aljazeera.com/xml/rss/all.xml',
    #          'http://defence-blog.com/feed',
    #          'https://www.e-ir.info/category/blogs/feed/',
    #          'https://www.globalissues.org/news/feed',
    #          'https://www.thecipherbrief.com/feed',
    #          'https://worldnewssuperfast.blogspot.com/feeds/posts/default?alt=rss',
    #          'http://rss.cnn.com/rss/edition_world.rss',
    #          'https://www.theguardian.com/world/rss',
    #          'http://feeds.washingtonpost.com/rss/world',
    #          'https://www.cnbc.com/id/100727362/device/rss/rss.html',
    #          'https://timesofindia.indiatimes.com/rssfeeds/296589292.cms',
    #          'https://www.cnbc.com/id/19746125/device/rss/rss.xml',
    #          'https://fortune.com/feed',
    #          'https://www.ft.com/?format=rss',
    #          'https://www.rfi.fr/fr/contenu/general/rss',
    #          'https://www.rfi.fr/afrique/rss',
    #          'https://www.rfi.fr/ameriques/rss',
    #          'https://www.rfi.fr/asie-pacifique/rss',
    #          'https://www.rfi.fr/europe/rss',
    #          'https://www.rfi.fr/france/rss',
    #          'https://www.rfi.fr/moyen-orient/rss',
    #          'https://www.rfi.fr/economie/rss',
    #          'https://www.rfi.fr/science/rss',
    #          'https://www.investing.com/rss/news.rss',
    #          'https://seekingalpha.com/market_currents.xml',
    #          'https://economictimes.indiatimes.com/rssfeedsdefault.cms',
    #          'https://finance.yahoo.com/news/rssindex',
    #          'https://www.financialexpress.com/feed/',
    #          'https://www.business-standard.com/rss/home_page_top_stories.rss',
    #          'https://www.thehindubusinessline.com/?service=rss',
    #          'https://prod-qt-images.s3.amazonaws.com/production/bloombergquint/feed.xml',
    #          # 'https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=1725',
    #          'https://www.moneyweb.co.za/feed/',
    #          'https://business.financialpost.com/feed/',
    #          'https://mjbizdaily.com/feed/',
    #          'https://www.bmmagazine.co.uk/feed/',
    #          'https://www.businessdailyafrica.com/latestrss.rss',
    #          'https://www.canadianbusiness.com/business-news/feed/',
    #          'https://www.yahoo.com/news/rss',
    #          # 'https://www.businesstravelnews.com/rss/business-travel-news',
    #          'http://rss.cnn.com/rss/money_topstories.rss',
    #          'https://businessday.ng/feed/',
    #          'https://www.biztrailblazer.com/feed',
    #          'https://www.revyuh.com/feed/',
    #          'http://businessnews.com.ng/feed/',
    #          'https://bbj.hu/site/assets/rss/rss.php',
    #          'http://www.birminghampost.co.uk/business/rss.xml',
    #          'https://www.businessnews.com.ph/feed/',
    #          'https://www.thailand-business-news.com/feed',
    #          'https://www.ibtimes.com.au/rss',
    #          'http://feeds.feedburner.com/JewishBusinessNews',
    #          'https://iotbusinessnews.com/feed/',
    #          'https://www.businessnews.com.au/rssfeed/latest.rss',
    #          'https://libn.com/feed/',
    #          'https://www.rt.com/rss/news/',
    #          'http://feeds.feedburner.com/ndtvnews-world-news',
    #          'http://www.npr.org/rss/rss.php?id=1004',
    #          'http://abcnews.go.com/abcnews/internationalheadlines',
    #          'https://www.spiegel.de/international/index.rss',
    #          'https://www.cbsnews.com/latest/rss/world',
    #          'https://sputniknews.com/export/rss2/world/index.xml',
    #          'http://www.independent.co.uk/news/world/rss',
    #          'http://www.cbc.ca/cmlink/rss-world',
    #          'https://www.abc.net.au/news/feed/52278/rss.xml',
    #          'http://feeds.feedburner.com/time/world',
    #          'https://time.com/feed',
    #          'https://www.thesun.co.uk/news/worldnews/feed/',
    #          'https://www.latimes.com/world/rss2.0.xml',
    #          'http://www.mirror.co.uk/news/world-news/rss.xml',
    #          'https://www.euronews.com/rss?level=theme&name=news',
    #          'https://www.vox.com/rss/world/index.xml',
    #          'http://feeds.skynews.com/feeds/rss/world.xml',
    #          'http://feeds.feedburner.com/daily-express-world-news',
    #          'http://www.smh.com.au/rssheadlines/world/article/rss.xml',
    #          'https://www.ctvnews.ca/rss/world/ctvnews-ca-world-public-rss-1.822289',
    #          # 'https://www.france24.com/en/rss',
    #          'https://www.scmp.com/rss/91/feed',
    #           'http://feeds.news24.com/articles/news24/World/rss',
    #          'https://globalnews.ca/world/feed/',
    #          'http://www.channelnewsasia.com/rssfeeds/8395884',
    #          'https://www.rawstory.com/category/world/feed/',
    #          'https://www.seattletimes.com/nation-world/world/feed/',
    #          'http://www.thestar.com/content/thestar/feed.RSSManagerServlet.articles.news.world.rss',
    #          # 'https://www.brookings.edu/topic/international-affairs/feed/',
    #          # 'http://www.washingtontimes.com/rss/headlines/news/world',
    #          # 'https://www.todayonline.com/feed/world',
    #          'https://www.dailytelegraph.com.au/news/world/rss',
    #          'https://feeds.breakingnews.ie/bnworld',
    #          # 'http://www1.cbn.com/cbnnews/world/feed'
    #          ]
    
    # feeds = []
    # for url in feedurls:
    #     feeds.append({'url':url, 'last':"", 'rss':{} })

    feeds = Scheduler.json_read('rssfeeds.conf')

    news = params['news']
    
    params['feeds'] = feeds
    params['TIMEOUT'] = 15
    
    async for res in fetch_news(params=params,control=control,news=news):
        url  = res['url']
        last = res['last']
        rss  = res['rss']
        nc = len(rss.keys())
        print('Recebendo os {num} resultados de fetchnew({url})'.format(url=url, num=nc))        

    # tem que atualizar os resultados da execução  agora, antes de gravar as atualizações.        
    Scheduler.json_write('rssfeeds.conf',feeds)

        # news = dict(sorted(news.items(), key=lambda t: news[ t[0] ]['timestamp'],reverse=True))
        
        # for rss_key in rss.keys():
        #     news = rss[rss_key]
        #     for news_id in news:
        #         print("News", news[news_id])
        #     news[rss_key] = news
   
        
        # print('news url:{url}: last article: {last} rss_ids_count:{nc}'.format(url=url,last=last,nc=nc))
     

    # res= await fetchall(params=params,control=control)    
    
    return res