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

import wx 
from wx import Frame, DefaultPosition, Size, Menu, MenuBar, App
from wx import EVT_MENU, EVT_CLOSE
import urllib.request 
import json
import webbrowser

from wxasync import AsyncBind, WxAsyncApp, StartCoroutine
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

class NewsPanel1(wx.Panel):

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.SetBackgroundColour("gray")


def dbCredentials():
    """Return SQLite database path"""
    db_path = config('DB_PATH', default='predator_news.db')
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path

def dbOpen():    
    db_path = dbCredentials()
    eng = create_engine(f'sqlite:///{db_path}')
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


class NewsPanel(wx.Panel):

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.SetBackgroundColour("gray")
        
        self.sources = dict()

        self.sources_list = wx.ListCtrl(
            self, 
            style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        self.sources_list.InsertColumn(0, "Source", width=200)
        
        self.getNewsSources()
        
        self.news_list = wx.ListCtrl(
            self, 
            size = (-1 , - 1),
            style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        self.news_list.InsertColumn(0, 'Link')
        self.news_list.InsertColumn(1, 'Title')
        self.news_list.InsertColumn(2, 'Hash url key')      
        
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.sources_list, 0, wx.ALL | wx.EXPAND)
        sizer.Add(self.news_list, 1, wx.ALL | wx.EXPAND)        
        self.SetSizer(sizer)

#        self.sources = self.getNewsSources()
        self.url_queue = Queue()
  
        self.sources_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnSourceSelected)
        self.news_list.Bind(wx.EVT_LIST_ITEM_SELECTED , self.OnLinkSelected)
        
        self.Bind(wx.EVT_PAINT, self.OnPaint)
        
        
#        self.sources = self.InitArticles(self.eng, self.meta, self.gm_sources,self.gm_articles)
        
#        StartCoroutine(self.async_getALLNews,self)
        self.UpdateNews()
        
    def UpdateArticles(self, eng, meta, gm_sources, gm_articles):
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
#                print("Article_key",article_key)
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
            wx.YieldIfNeeded()

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
            if source_id not in self.sources:
                self.sources_list.InsertItem(0, source[1])

        self.sources = sources
#        print(sources)
        return sources
        
    def OnPaint(self, evt):
        width, height = self.news_list.GetSize()
        for i in range(3):
            self.news_list.SetColumnWidth(i, width/3)
        evt.Skip()
    
    def OnSourceSelected(self, event):
         source = event.GetText() #.replace(" ", "-")
         self.news_list.DeleteAllItems()

         for key in self.sources:
            source_key          = key
            source_name         = self.sources[key]['name']
            source_url          = self.sources[key]['url']
            source_description  = self.sources[key]['description']
            source_articles     = self.sources[key]['articles']
            if source == source_name:
                print('source_key',source_key)
                print('source_name',source_name)
#                print('source_url',source_url)
#                print('source_description',source_description)
#                print('source_articles',source_articles)
                print('\n')
                index = 0
                for key in source_articles.keys():
                    self.news_list.InsertItem(index, source_articles[key]["url"])
                    self.news_list.SetItem(index, 1, source_articles[key]["title"])
                    self.news_list.SetItem(index, 2, key)
                    index += 1

         print('\n')
         
    
    def OnLinkSelected(self, event):
          print(event.GetText()) 
          webbrowser.open(event.GetText())           



    def UpdateNews(self):
#        self.InitQueue()   
        print("Refreshing news...")

        self.eng = dbOpen()
        self.meta = MetaData(self.eng)
        
        self.gm_sources = Table('gm_sources', self.meta, autoload=True) 
        self.gm_articles = Table('gm_articles', self.meta, autoload=True) 
  
        #self.news_list.DeleteAllItems()

        self.sources = self.UpdateArticles(self.eng, self.meta, self.gm_sources,self.gm_articles)
       
        wx.CallLater(60000*1, self.UpdateNews)

        

 
                     
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

class MainWindow(wx.Frame):
    def __init__(self, parent, title):

        super(MainWindow, self).__init__(parent, title = title, size = (600,500))
        self.Centre()


        NewsPanel(self)
        #self.panel.SetBackgroundColour("gray")
        self.createStatusBar()
        self.createMenu()


      
    def createStatusBar(self):
        self.CreateStatusBar() #A Statusbar at the bottom of the window


    def createMenu(self):
    
        menu= wx.Menu()
        menuExit = menu.Append(wx.ID_EXIT, "E&xit", "Quit application")

        menuBar = wx.MenuBar()
        menuBar.Append(menu,"&File")
        self.SetMenuBar(menuBar)

        self.Bind(wx.EVT_MENU, self.OnExit, menuExit)


    def OnExit(self, event):
        self.Close(True) 

class NewsGather(WxAsyncApp):

    def twoSecondsPassed(self):
        print("twenty seconds passed")
        wx.CallLater(20000, self.twoSecondsPassed)

    def OnInit(self):
        window = MainWindow(None, "Newsy - read worldwide news!")
        window.Show()
        self.SetTopWindow(window)
        # look, we can use twisted calls!
        wx.CallLater(2000, self.twoSecondsPassed)
        return True

if __name__ == '__main__':
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)   # register the App instance with Twisted:

    app = NewsGather(0)
    # start the event loop:
    loop = get_event_loop()
    loop.run_until_complete(app.MainLoop())
