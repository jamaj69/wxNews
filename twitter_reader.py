#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Dec 26 10:13:30 2020

@author: jamaj
"""
import asyncio
import asyncio
from peony import EventStream, PeonyClient, event_handler, events
import time
import math
import uuid
import json
import pprint
import Scheduler
from datetime import datetime
from dateutil.parser import parse 

# def json_read(json_file):
#     with open(json_file) as json_file:
#         data = json.load(json_file)
#     return(data)
from bs4 import BeautifulSoup

async def GetParsedURL(curl,session=None):
    html = await Scheduler.fetch(session,url=curl)
    erro = html['error']
    soup = None
    if erro:
        print('Erro {erro} em GetParsedURL({curl})'.format(erro=erro,curl=curl))
    else:
        html_doc = html['text']
        soup = BeautifulSoup(html_doc, 'html.parser')
    return soup

class asynctwitter:
    def __init__(self,creds,session):
        self.creds = creds
        self.session = session
        self.client = PeonyClient(**creds,session=session)
        

    async def gen(self,follow):
        async for tweet in self.track(follow):
            tweets ={}

            verified = tweet['user']['verified']
            if verified:
                pass
                # yield tweet,
                
            # print('Tweet:', tweet)
            
            if 'in_reply_to_status_id' in tweet and tweet['in_reply_to_status_id']:
                print('Tuite em reply')
                tid = tweet['in_reply_to_status_id']
                
                # tuite = await self.getStatusbyID(tid)
                
                # print('Tuite de usuário não verificado. Em reply tid: {tid}'.format(tid=tid))
                # print('tuite:',tweet)
                # print('tuite in-reply:',tuite)
                yield tweet
            elif 'retweeted_status' in tweet:                    
                print('Tuite retuitado')
                tid = tweet['id_str']
                # print('Tuite de usuário não verificado. Retwuite.')
                if 'retweeted_status' in tweet:
                    tuite = tweet['retweeted_status']
                else:
                    tuite = tweet
                # print('tuite retuitado:',tuite)
                yield tuite
            elif  tweet['is_quote_status']:
                print('Tuite mencionado')
     
                tid = tweet['id_str']
                if 'quoted_status' in tweet:
                    tuite = tweet['quoted_status']
                else:
                    tuite = tweet
                # print('tuite retuitado:',tuite)
                yield tuite
                 # print('Tuite de usuário não verificado. Menção.')
                 # print('tuite:',tweet)
            else:    
                print('Tuite comum')
                tid = tweet['id_str']
                tuite=tweet
                # print('Tuite de usuário não verificado. Decartado')
                # print('tuite:',tweet)
                yield tuite
            # # res = await process(tweet)
            # # print(tweet)
            # if  'feed' in tweet:
                
    async def process(self,follow,session=None):
        async for tweet in self.gen(follow):
            tid = tweet['id_str']
            text = tweet['text']
            created_at = tweet['created_at']
            new_datetime = parse(created_at)
            tweet['timestamp'] = new_datetime
            # pprint.pprint('Tweet:')
            # pprint.pprint(tweet)

            if 'extended_tweet' in tweet and 'entities' in tweet['extended_tweet']:
                urls = tweet['extended_tweet']['entities']['urls']
            elif 'entities' in tweet:
                urls = tweet['entities']['urls']
            else:
                urls = {}
                
            if urls:
                urls = urls[0]
                if 'url' in urls:
                    curl =  urls['url']
                    arq_name = Scheduler.GetShortURL(curl)
                    print('arq. name {arq_name}'.format(arq_name=arq_name))
                    soup = await GetParsedURL(curl,session=session)
                    if soup:
                        html_text = soup.prettify()

                if 'expanded_url' in urls:
                    curl =  urls['expanded_url']                    
                    arq_name = Scheduler.GetShortURL(curl)
                    print('arq. name {arq_name}'.format(arq_name=arq_name))
                    soup = await GetParsedURL(curl,session=session)
                    if soup:
                        html_text = soup.prettify()
                        with open('htmlpages/' + arq_name, "w") as f:
                            f.write(html_text)
                        # print(soup.prettify())
                
            res = { 'tid' : tid, 'text' : text, 'urls' : urls, 'tweet': tweet}
            yield res
            # duas coisas a faazer: armazenar ou mandar como mensagem ou para algum processamento.
    
    async def getStatusbyID( self, tid):
        res = await self.client.api.statuses.show.get(id=tid)
        return res
    
    async def track(self,follow):
        req = self.client.stream.statuses.filter.post(follow=follow)
        # req is an asynchronous context
        while True:
            async with req as stream:
                # stream is an asynchronous iterator
                try:
                    async for tweet in stream:
                        # check that you actually receive a tweet
                        if events.tweet(tweet):          
                            yield tweet
                except asyncio.TimeoutError as e:
                    print('Erro em twitter_reader.', str(e))
                    asyncio.sleep(1)
async def run(params,control):
    # CONSUMER_KEY = 'j1KOc2AWQ5QvrtNe8N15UfcXI'
    # CONSUMER_SECRET = 'AjHnwNBhBB1eegMcVYDvVBiQMAX6PHX9OOdqbqFSHHeezB9IJF'
    # ACCESS_TOKEN = '1201408473151496192-KZ2xMa2GSuanbi8UJtyFaH4XQ5foWa'
    # ACCESS_TOKEN_SECRET = 'rUgHWt9z252O0tX94GjO0Zs518NIWiCCXm1slluLX86T0'
    # USERIDS = [ '1201408473151496192','2923397967', '71567590', '24987917', '612896910', '1612504999', '15072071','41821987','41837261','348659640','59736898','219275799','18904582' ,'7996082','757809746','4898091']  

    # creds = dict(consumer_key=CONSUMER_KEY,
    #              consumer_secret=CONSUMER_SECRET,
    #              access_token=ACCESS_TOKEN,
    #              access_token_secret=ACCESS_TOKEN_SECRET)
    session = params['session']
    tuites  = params['tweets'] 
    translator = params['translator']

    while True:
        twitter_conf = Scheduler.json_read('twitter.conf')
        creds = twitter_conf['twitter']['creds']
        userids = twitter_conf['twitter']['userids']
    
        # twitter_conf = { 'twitter': { 'creds': twitter_creds, 'userids': USERIDS } }
        # json_write('twitter.conf',twitter_conf)
        
        twitter_reader = asynctwitter(creds,session)
        
        async for res in twitter_reader.process(userids,session=session):
            tid = res['tid']
            text = res['text']
            urls = res['urls']
            trans = res['text']
            trans = await Scheduler.Translate(res['text'],session=session)
            res['translations'] = trans
            trans = res['translations']
            if not tid in tuites.keys():
                tuites[tid] = res            
                print('tuite: id: {tid} text: {text} urls: {urls} translation: {trans}'.format(tid=tid,text=text,urls=urls, trans = trans))            
        
    # res = await twitter_reader.process(userids)
    
                
if __name__ == "__main__":

    loop = asyncio.get_event_loop()
    loop.run_until_complete(run())
