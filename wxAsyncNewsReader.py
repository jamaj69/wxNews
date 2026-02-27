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
import wx.html2
import urllib.request 
import json
import webbrowser
from datetime import datetime

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

# Only API_KEY1 is used by the reader (for getNewsSources)
API_KEY1 = config('NEWS_API_KEY_1')


def url_encode(url):
    return base64.urlsafe_b64encode(zlib.compress(url.encode('utf-8')))[15:31]

class NewsPanel1(wx.Panel):

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.SetBackgroundColour("gray")


class ArticleDetailFrame(wx.Frame):
    """Frame to display full article details with text and image"""
    
    def __init__(self, parent, article_data):
        super(ArticleDetailFrame, self).__init__(
            parent, 
            title=article_data.get('title', 'Article Details')[:100],
            size=(900, 700)
        )
        
        self.article_data = article_data
        self.Centre()
        
        # Create main panel
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Title
        title = article_data.get('title', 'No Title')
        title_text = wx.StaticText(panel, label=title)
        title_font = title_text.GetFont()
        title_font.PointSize += 4
        title_font = title_font.Bold()
        title_text.SetFont(title_font)
        title_text.Wrap(850)
        main_sizer.Add(title_text, 0, wx.ALL|wx.EXPAND, 10)
        
        # Metadata line (Author, Date, Source)
        metadata_parts = []
        if article_data.get('author'):
            metadata_parts.append(f"Author: {article_data['author']}")
        if article_data.get('publishedAt'):
            try:
                pub_date = datetime.fromisoformat(article_data['publishedAt'].replace('Z', '+00:00'))
                metadata_parts.append(f"Published: {pub_date.strftime('%Y-%m-%d %H:%M')}")
            except:
                metadata_parts.append(f"Published: {article_data['publishedAt']}")
        if article_data.get('id_source'):
            metadata_parts.append(f"Source: {article_data['id_source']}")
        
        if metadata_parts:
            metadata_text = wx.StaticText(panel, label=" | ".join(metadata_parts))
            metadata_font = metadata_text.GetFont()
            metadata_font.PointSize -= 1
            metadata_text.SetFont(metadata_font)
            metadata_text.SetForegroundColour(wx.Colour(100, 100, 100))
            main_sizer.Add(metadata_text, 0, wx.LEFT|wx.RIGHT|wx.BOTTOM|wx.EXPAND, 10)
        
        # Separator
        main_sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND|wx.ALL, 5)
        
        # Image (if available)
        image_url = article_data.get('urlToImage')
        if image_url and image_url.strip():
            try:
                # Try to load image from URL
                import io
                from PIL import Image as PILImage
                import urllib.request
                
                req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    image_data = response.read()
                    image_stream = io.BytesIO(image_data)
                    pil_image = PILImage.open(image_stream)
                    
                    # Resize if too large
                    max_width = 850
                    if pil_image.width > max_width:
                        ratio = max_width / pil_image.width
                        new_height = int(pil_image.height * ratio)
                        pil_image = pil_image.resize((max_width, new_height), PILImage.Resampling.LANCZOS)
                    
                    # Convert to wx.Image
                    width, height = pil_image.size
                    wx_image = wx.Image(width, height)
                    wx_image.SetData(pil_image.convert("RGB").tobytes())
                    
                    # Display image
                    bitmap = wx.StaticBitmap(panel, bitmap=wx.Bitmap(wx_image))
                    main_sizer.Add(bitmap, 0, wx.ALL|wx.ALIGN_CENTER, 10)
            except Exception as e:
                # If image loading fails, show placeholder
                error_text = wx.StaticText(panel, label=f"[Image unavailable: {str(e)[:50]}]")
                error_text.SetForegroundColour(wx.Colour(150, 150, 150))
                main_sizer.Add(error_text, 0, wx.ALL, 10)
        
        # Description
        description = article_data.get('description', '')
        if description and description.strip():
            desc_text = wx.StaticText(panel, label=description)
            desc_font = desc_text.GetFont()
            desc_font.PointSize += 1
            desc_text.SetFont(desc_font)
            desc_text.Wrap(850)
            main_sizer.Add(desc_text, 0, wx.ALL|wx.EXPAND, 10)
        
        # Content
        content = article_data.get('content', '')
        if content and content.strip():
            main_sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND|wx.ALL, 5)
            content_label = wx.StaticText(panel, label="Content:")
            content_label_font = content_label.GetFont().Bold()
            content_label.SetFont(content_label_font)
            main_sizer.Add(content_label, 0, wx.LEFT|wx.TOP, 10)
            
            content_text = wx.TextCtrl(
                panel, 
                value=content,
                style=wx.TE_MULTILINE|wx.TE_READONLY|wx.TE_WORDWRAP
            )
            main_sizer.Add(content_text, 1, wx.ALL|wx.EXPAND, 10)
        else:
            # Add spacer if no content
            main_sizer.AddStretchSpacer()
        
        # Button panel
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Open in Browser button
        url = article_data.get('url', '')
        if url:
            open_btn = wx.Button(panel, label="Open Full Article in Browser")
            open_btn.Bind(wx.EVT_BUTTON, lambda evt: webbrowser.open(url))
            button_sizer.Add(open_btn, 0, wx.ALL, 5)
        
        # Close button
        close_btn = wx.Button(panel, wx.ID_CLOSE, "Close")
        close_btn.Bind(wx.EVT_BUTTON, lambda evt: self.Close())
        button_sizer.Add(close_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(button_sizer, 0, wx.ALL|wx.ALIGN_CENTER, 10)
        
        panel.SetSizer(main_sizer)
        
        # Keyboard shortcuts
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyPress)
        
    def OnKeyPress(self, event):
        """Handle keyboard shortcuts"""
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()


def dbCredentials():
    """Return SQLite database path"""
    db_path = config('DB_PATH', default='predator_news.db')
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path

def dbOpen():    
    db_path = dbCredentials()
    # SQLite connection string with timeout to prevent "database is locked" 
    eng = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False},
        pool_pre_ping=True
    )

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

    return eng


class NewsPanel(wx.Panel):

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.SetBackgroundColour("gray")
        
        self.sources = dict()
        self.current_source_key = None  # Track currently selected source

        self.sources_list = wx.ListCtrl(
            self, 
            style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        self.sources_list.InsertColumn(0, "Source", width=200)
        
        # Don't call getNewsSources() - load from database instead
        # self.getNewsSources()
        
        self.news_list = wx.ListCtrl(
            self, 
            size = (-1 , - 1),
            style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        self.news_list.InsertColumn(0, 'URL')
        self.news_list.InsertColumn(1, 'Title')
        self.news_list.InsertColumn(2, 'Article ID')      
        self.news_list.InsertColumn(3, 'Published')      
        
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.sources_list, 0, wx.ALL | wx.EXPAND)
        sizer.Add(self.news_list, 1, wx.ALL | wx.EXPAND)        
        self.SetSizer(sizer)

#        self.sources = self.getNewsSources()
        self.url_queue = Queue()
  
        self.sources_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnSourceSelected)
        self.news_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnLinkSelected)  # Double-click to open details
        
        self.Bind(wx.EVT_PAINT, self.OnPaint)
        
        
#        self.sources = self.InitArticles(self.eng, self.meta, self.gm_sources,self.gm_articles)
        
#        StartCoroutine(self.async_getALLNews,self)
        self.UpdateNews()
        
    def UpdateArticles(self, eng, meta, gm_sources, gm_articles):
        sources = dict()
        
        # Track if this is first load (self.sources is empty)
        is_first_load = len(self.sources) == 0
        
        if is_first_load:
            print("First load - clearing sources list")
            self.sources_list.DeleteAllItems()
        
        # Configuration: Minimum articles to show a source
        MIN_ARTICLES = 10  # Only show sources with at least 10 articles
        MAX_SOURCES = 50   # Show maximum 50 sources
        
        con = eng.connect()
        stm = select(gm_sources)
        rs = con.execute(stm)
        
        # First pass: count articles per source (lightweight)
        source_list = []
        for source in rs.fetchall():
            source_id = source[0]
            # Use COUNT to get article count efficiently
            from sqlalchemy import func
            stm1 = select(func.count()).select_from(gm_articles).where(gm_articles.c.id_source == source_id)
            article_count = con.execute(stm1).scalar()
            
            # Only keep sources with minimum article count AND non-empty names
            source_name = source[1] if source[1] else ""
            if article_count >= MIN_ARTICLES and source_name.strip():
                source_list.append({
                    'source_id': source_id,
                    'source_name': source_name.strip(),
                    'source_data': source,
                    'article_count': article_count
                })
            
            wx.YieldIfNeeded()
        
        # Sort by article count (most articles first)
        source_list.sort(key=lambda x: x['article_count'], reverse=True)
        
        # Limit to top N sources
        source_list = source_list[:MAX_SOURCES]
        
        print(f"Filtered to {len(source_list)} sources (min {MIN_ARTICLES} articles, max {MAX_SOURCES} sources)")
        
        # Second pass: load full articles ONLY for filtered sources
        for item in source_list:
            source_id = item['source_id']
            source = item['source_data']
            
            # Now load the actual articles
            stm2 = select(gm_articles).where(gm_articles.c.id_source == source_id)
            articles_qry = con.execute(stm2)
            articles = dict()
            for article in articles_qry.fetchall():
                article_key = article[0]
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
            item['articles'] = articles
            
            print(f"Source: {item['source_name']} ({item['article_count']} articles)")
            
            # Use the stripped source name consistently
            source_name = item['source_name']
            
            sources[source_id] = { 
                    'id_source': source_id,
                    'name': source_name,  # Use stripped name
                    'description': source[2],
                    'url': source[3],
                    'category': source[4],
                    'language': source[5],
                    'country': source[6],
                    'articles': item['articles']
                 }
            
            # Add to list
            if is_first_load:
                self.sources_list.InsertItem(self.sources_list.GetItemCount(), f"{source_name} ({item['article_count']})")
            elif source_id not in self.sources:
                self.sources_list.InsertItem(0, f"{source_name} ({item['article_count']})")

        self.sources = sources
        print(f"Showing {len(sources)} sources with {sum(len(s['articles']) for s in sources.values())} total articles")
#        print(sources)
        return sources
        
    def OnPaint(self, evt):
        width, height = self.news_list.GetSize()
        for i in range(4):
            self.news_list.SetColumnWidth(i, int(width/4))
        evt.Skip()
    
    def OnSourceSelected(self, event):
         source_text = event.GetText()
         # Strip article count from source name (format: "Source Name (123)")
         if '(' in source_text:
             source = source_text.rsplit(' (', 1)[0]
         else:
             source = source_text
         
         print(f"\n=== Source Selected ===")
         print(f"Display text: '{source_text}'")
         print(f"Parsed name: '{source}'")
         print(f"Available sources: {len(self.sources)}")
         
         self.news_list.DeleteAllItems()
         self.current_source_key = None  # Track current source
         
         found = False
         for key in self.sources:
            source_key          = key
            source_name         = self.sources[key]['name']
            source_url          = self.sources[key]['url']
            source_description  = self.sources[key]['description']
            source_articles     = self.sources[key]['articles']
            
            print(f"  Checking: '{source_name}' == '{source}' ? {source_name == source}")
            
            if source == source_name:
                found = True
                self.current_source_key = source_key  # Save for article selection
                print(f'✓ MATCH! source_key: {source_key}')
                print(f'  Articles: {len(source_articles)}')
#                print('source_url',source_url)
#                print('source_description',source_description)
#                print('source_articles',source_articles)
                
                index = 0
                for key in source_articles.keys():
                    self.news_list.InsertItem(index, source_articles[key]["url"])
                    self.news_list.SetItem(index, 1, source_articles[key]["title"])
                    self.news_list.SetItem(index, 2, key)
                    self.news_list.SetItem(index, 3, source_articles[key]["publishedAt"])
                    index += 1
                
                print(f'✓ Inserted {index} articles into news_list')
                break  # Exit loop after finding match
         
         if not found:
             print(f'✗ NO MATCH FOUND for: "{source}"')
         
         print('='*50 + '\n')
         
    
    def OnLinkSelected(self, event):
        """Open article detail frame when article is double-clicked"""
        # Get selected item index
        selected_index = event.GetIndex()
        
        # Get article key from column 2
        article_key = self.news_list.GetItem(selected_index, 2).GetText()
        
        # Get article data from sources
        if hasattr(self, 'current_source_key') and self.current_source_key:
            source = self.sources.get(self.current_source_key)
            if source:
                article_data = source['articles'].get(article_key)
                if article_data:
                    # Open detail frame
                    detail_frame = ArticleDetailFrame(self, article_data)
                    detail_frame.Show()
                else:
                    print(f"Article {article_key} not found")
            else:
                print(f"Source {self.current_source_key} not found")
        else:
            # Fallback: open URL in browser
            url = self.news_list.GetItem(selected_index, 0).GetText()
            if url:
                webbrowser.open(url)           



    def UpdateNews(self):
#        self.InitQueue()   
        print("Refreshing news...")

        self.eng = dbOpen()
        self.meta = MetaData()
        
        self.gm_sources = Table('gm_sources', self.meta, autoload_with=self.eng) 
        self.gm_articles = Table('gm_articles', self.meta, autoload_with=self.eng) 
  
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
