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

def json_write(json_file,data):
    with open(json_file, 'w') as outfile:
        json.dump(data, outfile)
    return(data)

def json_read(json_file):
    with open(json_file) as json_file:
        data = json.load(json_file)
    return(data)

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

async def fetch_url(params=None,control=None):
    url = params['url']
    session = params['session']
    keys = params['keys']
    control = params['control']    
    print('newsapi > fetch_url')
    print('url:', url)
    print('keys:', keys)    
    
    res = await fetch(session, url)        
    if res:
        news_list = json_load(res)
        pprint(news_list)
    else:
        pass
    
    return res


    
async def news_gather(params=None,control=None):
    last_entry = None
    urls = params['URLS']
    keys = params['KEYS']
    session = params['session']

    print('Entrando em news_gather')

    while True:
        tasks = []
        for url in urls:           
            print('url',url)
            params = { 'session': session, 'url': url, 'keys': keys, 'control':control }
            task = control.add_task(func=fetch_url,params=params)
            # print('create process')
            tasks.append(task)
            await asyncio.sleep(0)
        task_group = [ task.run() for task in tasks ]
        # res = await control.runtasks(tasks)
        # print('fetchall tasks:',task_group)
        ress = await control.runtasks(tasks)
        
        for res in ress:
            print('Resultado >', res )
            
        print('await.sleep...')

        # control.return_finish(result=feeds)
        # reschedule
        # control.return_reschedule(NTERVAL,result=feedurls)
        await asyncio.sleep(INTERVAL)


async def run(params,control):
    newsapi_conf = {'keys': [ {'email': 'predator@jamaj.com.br', 'key': 'c85890894ddd4939a27c19a3eff25ece'},
                              {'email': 'jamaj@jamaj.com.br', 'key': '4327173775a746e9b4f2632af3933a86'},
                            {'email': 'predator_corp@jamaj.com.br', 'key': '04b7b4e6770442cab42a9e312c8d9e58'},
                            {'email': 'predator_politics@jamaj.com.br','key': 'fc1ed4bcc4b145499b249a00bd5f5481'},
                            {'email': 'predator_newsapi@jamaj.com.br','key': 'b9ff8a2ce16748be9caea2662ba0a0b0'} ],
                    'refresh_period_sec': 600 }
    
    json_write('newsapi.conf',newsapi_conf)
    
    conf = json_read('predator/conf.dat')
    newsapi_conf = conf['news_api']
    NEWS_API_KEYS = [ x['key'] for x in conf['news_api']['keys'] ] 
    
    urls = [ "https://newsapi.org/v2/top-headlines?language=en&pageSize=100&apiKey=" ,
             "https://newsapi.org/v2/top-headlines?language=pt&pageSize=100&apiKey=" ,
             "https://newsapi.org/v2/top-headlines?language=es&pageSize=100&apiKey=" ,
             "https://newsapi.org/v2/top-headlines?language=it&pageSize=100&apiKey=" ,
             "https://newsapi.org/v2/top-headlines?sources=google-news-uk&pageSize=100&apiKey=",
             "https://newsapi.org/v2/top-headlines?sources=vice-news&pageSize=100&apiKey="
            ]
    
    # params =    {  }
    params['URLS'] = urls
    params['KEYS'] = NEWS_API_KEYS
    
    res= await news_gather(params=params,control=control)    
    
return res

if __name__ == "__main__":  
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    