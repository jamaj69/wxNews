#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jan  4 11:23:38 2021

@author: jamaj
"""
import json
from pprint import pprint
import Scheduler
import asyncio
import random
import async_timeout
import ast
import arrow
import datetime

# def json_write(json_file,data):
#     with open(json_file, 'w') as outfile:
#         json.dump(data, outfile)
#     return(data)

# def json_read(json_file):
#     with open(json_file) as json_file:
#         data = json.load(json_file)
#     return(data)

# async def fetch(session, url):
#     res = {}
#     res['url'] = url
#     res['error'] = ""
#     res['text'] = ""
#     res['stat'] = 0
#     with async_timeout.timeout(10):
#         try:
#             async with session.get(url) as response:
#                 res['stat']  = response.status
#                 # print("Headers:  ",response.headers)
#                 res['text']  = await response.text()            
#         except aiohttp.ClientConnectorError as e:
#             error = res['error'] = str(e)
#             print('Connection Error. url: {url}. error: {error}'.format(**res) )
#         except asyncio.TimeoutError as e:
#             error = res['error'] = str(e)
#             print('Timeout Error. url: {url}. error: {error}'.format(**res) )
#         except Exception as e:
#             error = res['error'] = str(e)
#             print('General Error. url: {url}. error: {error}'.format(**res) )
#         finally:
#             return res

async def fetch_url(params=None,control=None):
    url = params['url']
    session = params['session']
    keys = params['keys']
    control = params['control'] 
    news = params['news']
  
    

    print('newsapi > fetch_url {url}'.format(url=url))
    # print('fetch res:', res)
    # print('url:', url)
    # print('keys:', keys)    

    res = await Scheduler.fetch(session, url + random.choice(keys))

    error = res['error']
    news_str = res['text']

    # print('news_str type = ',type(news_str))
    
    
    if error:
        print(error) 
        article = ""        
    else:
        # news = ast.literal_eval(res['text'])
        rss = json.loads(news_str)
    # print(news)        
    if rss:
        status = rss['status']
        # totalResults = news['totalResults']
        if status == 'ok':
            if 'articles' in rss:
                articles = rss['articles']                
                for article in articles:
                    id_news =  Scheduler.GetShortURL(article['url'])
                    url_news =  article['url']
                    if id_news in news:
                        print('Artigo já inserido em news.')
                    else:
                        print('Inserir artigo {id_news} news.'.format(id_news=id_news))
                        article['id'] = id_news
                        # article['timestamp'] = arrow.get(article['publishedAt']).datetime.strftime("%Y-%m-%dT%H:%M:%SZ")  
                        article['timestamp'] = Scheduler.Norm_DateTime(article['publishedAt'])
                                      
                        article['summary'] = {}
                        article['summary']['value'] = article['content']

                        article['title1'] = {}
                        article['title1']['value'] = article['title']
                        article['title'] = article['title1']
                        article['link'] = article['url']
                        
                        print('O arquivo news tem agora {tam} artigos.'.format(tam=len(news.keys())))
                        news[id_news] = article
                        
                        
                        pprint(article)
                        
        else:
            print('Erro em ',res)
            pass


            
        # async for article in articles:
        #     pprint(article)
        pass       
    else:
        pass
    
    return res


    
async def news_gather(params=None,control=None):
    last_entry = None
    urls = params['URLS']
    keys = params['KEYS']
    session = params['session']
    INTERVAL = params['INTERVAL']
    news = params['news']

    print('Entrando em news_gather. Interval:', INTERVAL)
    print('Entrando em news_gather. URLS:', urls)


    tasks = []
    for url in urls:           
        print('news_gather url',url)
        params = { 'session': session, 'url': url, 'keys': keys, 'control':control, 'news' : news }
        task = control.add_task(func=fetch_url,params=params)
        # print('create process')
        tasks.append(task)
  
    ress = await control.runtasks(tasks)
    
    for res in ress:
        pass
        # print('Resultado >', res )
        
    return res

async def run(params,control):


    newsapi_conf = {'keys': [ {'email': 'predator@jamaj.com.br', 'key': 'c85890894ddd4939a27c19a3eff25ece'},
                              {'email': 'jamaj@jamaj.com.br', 'key': '4327173775a746e9b4f2632af3933a86'},
                            {'email': 'predator_corp@jamaj.com.br', 'key': '04b7b4e6770442cab42a9e312c8d9e58'},
                            {'email': 'predator_politics@jamaj.com.br','key': 'fc1ed4bcc4b145499b249a00bd5f5481'},
                            {'email': 'predator_newsapi@jamaj.com.br','key': 'b9ff8a2ce16748be9caea2662ba0a0b0'} ],
                    'refresh_period_sec': 600 }
    
    Scheduler.json_write('newsapi.conf',newsapi_conf)
    
    conf = Scheduler.json_read('predator/conf.dat')
    newsapi_conf = conf['news_api']
    NEWS_API_KEYS = [ x['key'] for x in conf['news_api']['keys'] ] 
    
    urls = [ "https://newsapi.org/v2/top-headlines?language=en&pageSize=20&apiKey=" ,
             "https://newsapi.org/v2/top-headlines?language=pt&pageSize=20&apiKey=" ,
             "https://newsapi.org/v2/top-headlines?language=es&pageSize=20&apiKey=" ,
             "https://newsapi.org/v2/top-headlines?language=it&pageSize=20&apiKey=" ,
             "https://newsapi.org/v2/top-headlines?sources=google-news-uk&pageSize=20&apiKey=",
            ]
    
    while True:
    # params =    {  }
        params['URLS'] = urls
        params['KEYS'] = NEWS_API_KEYS
        INTERVAL = params['INTERVAL'] = 60 * 10
        
        res= await news_gather(params=params,control=control)    
        print('await.sleep...')
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":  
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    