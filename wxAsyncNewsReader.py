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
from dateutil import parser as date_parser

from wxasync import AsyncBind, WxAsyncApp, StartCoroutine
import asyncio, aiohttp
from asyncio.events import get_event_loop
import time
import base64
import zlib
from article_fetcher import fetch_article_content

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
    """Frame to display full article details with metadata fields and HTML viewer"""
    
    def __init__(self, parent, article_data, source_name=''):
        super(ArticleDetailFrame, self).__init__(
            parent, 
            title=article_data.get('title', 'Article Details')[:100],
            size=(1000, 800)
        )
        
        self.article_data = article_data
        self.source_name = source_name
        self.Centre()
        
        # Create main panel
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # === METADATA SECTION AT TOP ===
        metadata_panel = wx.Panel(panel)
        metadata_panel.SetBackgroundColour(wx.Colour(255, 255, 255))  # White background for better contrast
        metadata_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Title
        title = article_data.get('title', 'No Title')
        title_text = wx.StaticText(metadata_panel, label=title)
        title_font = title_text.GetFont()
        title_font.PointSize += 3
        title_font = title_font.Bold()
        title_text.SetFont(title_font)
        title_text.SetForegroundColour(wx.Colour(0, 0, 0))  # Black text
        title_text.Wrap(950)
        metadata_sizer.Add(title_text, 0, wx.ALL|wx.EXPAND, 10)
        
        # Separator line
        line1 = wx.StaticLine(metadata_panel)
        metadata_sizer.Add(line1, 0, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)
        
        # Metadata fields in a grid
        fields_sizer = wx.FlexGridSizer(cols=2, hgap=15, vgap=8)
        fields_sizer.AddGrowableCol(1, 1)
        
        # Source/Origin
        source_label = wx.StaticText(metadata_panel, label="Source:")
        source_label.SetFont(source_label.GetFont().Bold())
        source_label.SetForegroundColour(wx.Colour(60, 60, 60))  # Dark gray
        fields_sizer.Add(source_label, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL)
        source_value = self.source_name if self.source_name else article_data.get('id_source', 'N/A')
        source_text = wx.StaticText(metadata_panel, label=source_value)
        source_text.SetForegroundColour(wx.Colour(0, 0, 0))  # Black
        fields_sizer.Add(source_text, 0, wx.EXPAND)
        
        # Author
        author_label = wx.StaticText(metadata_panel, label="Author:")
        author_label.SetFont(author_label.GetFont().Bold())
        author_label.SetForegroundColour(wx.Colour(60, 60, 60))
        fields_sizer.Add(author_label, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL)
        author = article_data.get('author', 'N/A') if article_data.get('author') else 'N/A'
        author_text = wx.StaticText(metadata_panel, label=author)
        author_text.SetForegroundColour(wx.Colour(0, 0, 0))
        fields_sizer.Add(author_text, 0, wx.EXPAND)
        
        # Published date/time
        pub_label = wx.StaticText(metadata_panel, label="Published:")
        pub_label.SetFont(pub_label.GetFont().Bold())
        pub_label.SetForegroundColour(wx.Colour(60, 60, 60))
        fields_sizer.Add(pub_label, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL)
        published = article_data.get('publishedAt', 'N/A')
        if published and published != 'N/A':
            try:
                pub_date = datetime.fromisoformat(published.replace('Z', '+00:00'))
                published = pub_date.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
        pub_text = wx.StaticText(metadata_panel, label=published)
        pub_text.SetForegroundColour(wx.Colour(0, 0, 0))
        fields_sizer.Add(pub_text, 0, wx.EXPAND)
        
        # URL
        url_label = wx.StaticText(metadata_panel, label="URL:")
        url_label.SetFont(url_label.GetFont().Bold())
        url_label.SetForegroundColour(wx.Colour(60, 60, 60))
        fields_sizer.Add(url_label, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL)
        url = article_data.get('url', 'N/A')
        url_text = wx.StaticText(metadata_panel, label=url)
        url_text.SetForegroundColour(wx.Colour(0, 100, 200))  # Blue for links
        url_text.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        if url and url != 'N/A':
            url_text.Bind(wx.EVT_LEFT_DOWN, lambda evt: webbrowser.open(url))
        fields_sizer.Add(url_text, 0, wx.EXPAND)
        
        # Image URL (if available)
        image_url = article_data.get('urlToImage', '')
        if image_url and image_url.strip():
            img_label = wx.StaticText(metadata_panel, label="Image URL:")
            img_label.SetFont(img_label.GetFont().Bold())
            img_label.SetForegroundColour(wx.Colour(60, 60, 60))
            fields_sizer.Add(img_label, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL)
            img_url_text = wx.StaticText(metadata_panel, label=image_url)
            img_url_text.SetForegroundColour(wx.Colour(0, 100, 200))  # Blue for links
            img_url_text.SetCursor(wx.Cursor(wx.CURSOR_HAND))
            img_url_text.Bind(wx.EVT_LEFT_DOWN, lambda evt: webbrowser.open(image_url))
            fields_sizer.Add(img_url_text, 0, wx.EXPAND)
        
        metadata_sizer.Add(fields_sizer, 0, wx.ALL|wx.EXPAND, 10)
        
        # Separator line at bottom
        line2 = wx.StaticLine(metadata_panel)
        metadata_sizer.Add(line2, 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, 10)
        
        metadata_panel.SetSizer(metadata_sizer)
        main_sizer.Add(metadata_panel, 0, wx.ALL|wx.EXPAND, 5)
        
        # === HTML VIEWER SECTION AT BOTTOM ===
        html_label = wx.StaticText(panel, label="Article Content:")
        html_label_font = html_label.GetFont().Bold()
        html_label.SetFont(html_label_font)
        main_sizer.Add(html_label, 0, wx.LEFT|wx.TOP, 10)
        
        # Create HTML viewer
        self.html_viewer = wx.html2.WebView.New(panel)
        
        # Build HTML content from article data
        html_content = self._build_html_content()
        self.html_viewer.SetPage(html_content, "")
        
        main_sizer.Add(self.html_viewer, 1, wx.ALL|wx.EXPAND, 10)
        
        # Button panel
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Fetch Content button (if content is missing)
        description = article_data.get('description', '')
        content = article_data.get('content', '')
        url = article_data.get('url', '')
        
        if url and not (description and description.strip()) and not (content and content.strip()):
            fetch_btn = wx.Button(panel, label="🔄 Fetch Missing Content")
            fetch_btn.Bind(wx.EVT_BUTTON, self.OnFetchContent)
            button_sizer.Add(fetch_btn, 0, wx.ALL, 5)
        
        # Open in Browser button
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
        
    def _build_html_content(self):
        """Build HTML content from article data"""
        description = self.article_data.get('description', '')
        content = self.article_data.get('content', '')
        image_url = self.article_data.get('urlToImage', '')
        url = self.article_data.get('url', '')
        
        html = '''<!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    padding: 20px;
                    line-height: 1.6;
                    color: #333;
                    background-color: #fff;
                }
                img {
                    max-width: 100%;
                    height: auto;
                    display: block;
                    margin: 20px auto;
                    border-radius: 8px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }
                .description {
                    font-size: 1.1em;
                    font-weight: 500;
                    margin-bottom: 20px;
                    color: #444;
                }
                .content {
                    font-size: 1em;
                    margin-top: 20px;
                    text-align: justify;
                }
                .read-more {
                    margin-top: 30px;
                    padding: 10px 20px;
                    background-color: #007bff;
                    color: white;
                    text-decoration: none;
                    border-radius: 5px;
                    display: inline-block;
                }
                .read-more:hover {
                    background-color: #0056b3;
                }
                .no-content {
                    color: #999;
                    font-style: italic;
                    text-align: center;
                    padding: 40px;
                }
            </style>
        </head>
        <body>
        '''
        
        # Add image if available
        if image_url and image_url.strip():
            html += f'<img src="{image_url}" alt="Article image" onerror="this.style.display=\'none\'"/>'
        
        # Add description
        has_description = description and description.strip()
        if has_description:
            html += f'<div class="description">{description}</div>'
        
        # Add content
        has_content = content and content.strip()
        if has_content:
            # Replace newlines with <br> for better formatting
            content_html = content.replace('\n', '<br>')
            html += f'<div class="content">{content_html}</div>'
        
        # If no content, show message
        if not has_description and not has_content:
            html += '<div class="no-content">📄 No article content available in database.<br><br>This article may only provide a title and link in the RSS feed.<br><br>💡 <b>Tip:</b> Click the "🔄 Fetch Missing Content" button above to automatically extract content from the article webpage.<br><br>Or click "Open Full Article in Browser" below to read the full content on the original site.</div>'
        
        # Add link to full article
        if url and url.strip():
            html += f'<br><a href="{url}" class="read-more" target="_blank">Open Full Article in Browser</a>'
        
        html += '</body></html>'
        return html
    
    def OnKeyPress(self, event):
        """Handle keyboard shortcuts"""
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()
    
    def OnFetchContent(self, event):
        """Fetch missing content from the article URL"""
        url = self.article_data.get('url', '')
        if not url:
            wx.MessageBox("No URL available to fetch content from.", "Error", wx.OK | wx.ICON_ERROR)
            return
        
        # Show progress dialog
        progress = wx.ProgressDialog(
            "Fetching Content",
            f"Fetching article content from:\n{url[:60]}...",
            maximum=100,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        progress.Pulse("Requesting webpage...")
        
        try:
            # Fetch content (this might take a few seconds)
            wx.Yield()  # Allow UI to update
            result = fetch_article_content(url, timeout=15)
            
            if result['success']:
                # Update article data with fetched content
                if result['author'] and not self.article_data.get('author'):
                    self.article_data['author'] = result['author']
                
                if result['published_time'] and not self.article_data.get('publishedAt'):
                    self.article_data['publishedAt'] = result['published_time']
                
                if result['description']:
                    self.article_data['description'] = result['description']
                
                if result['content']:
                    self.article_data['content'] = result['content']
                
                # Rebuild and refresh HTML content
                html_content = self._build_html_content()
                self.html_viewer.SetPage(html_content, "")
                
                # Update metadata display
                author_text = self.article_data.get('author', 'Unknown')
                published_text = self.article_data.get('publishedAt', 'Unknown')
                
                # Find and update the metadata panel
                for child in self.GetChildren():
                    if isinstance(child, wx.Panel):
                        for subchild in child.GetChildren():
                            if isinstance(subchild, wx.Panel):
                                # This is likely the metadata panel
                                for item in subchild.GetChildren():
                                    if isinstance(item, wx.StaticText):
                                        text = item.GetLabel()
                                        if text.startswith('Author:'):
                                            item.SetLabel(f'Author: {author_text}')
                                        elif text.startswith('Published:'):
                                            item.SetLabel(f'Published: {published_text}')
                
                progress.Update(100)
                wx.MessageBox(
                    f"Successfully fetched content!\n\nAuthor: {result['author'] or 'Not found'}\n"
                    f"Published: {result['published_time'] or 'Not found'}\n"
                    f"Content: {'Found' if result['content'] else 'Not found'}",
                    "Success",
                    wx.OK | wx.ICON_INFORMATION
                )
            else:
                progress.Update(100)
                wx.MessageBox(
                    "Failed to fetch content from the article URL.\n\n"
                    "This could be due to:\n"
                    "- Paywall or login required\n"
                    "- Website blocking automated access\n"
                    "- Network connectivity issues\n"
                    "- Page structure not supported",
                    "Fetch Failed",
                    wx.OK | wx.ICON_WARNING
                )
                
        except Exception as e:
            progress.Update(100)
            wx.MessageBox(
                f"Error fetching content:\n{str(e)}",
                "Error",
                wx.OK | wx.ICON_ERROR
            )
        finally:
            progress.Destroy()


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
        self.all_articles = []  # Store all articles for "All News" mode
        self.current_source_key = None  # Track currently selected source
        self.populating_list = False  # Flag to prevent event firing during list population
        self.view_mode = 'source'  # 'source' or 'all'

        # Create main vertical sizer
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # === MODE SELECTOR PANEL ===
        mode_panel = wx.Panel(self)
        mode_panel.SetBackgroundColour(wx.Colour(240, 240, 240))
        mode_panel.SetMinSize((-1, 50))  # Fixed minimum height to prevent blinking
        mode_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        mode_label = wx.StaticText(mode_panel, label="View Mode:")
        mode_label_font = mode_label.GetFont()
        mode_label_font = mode_label_font.Bold()
        mode_label.SetFont(mode_label_font)
        mode_sizer.Add(mode_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)
        
        self.mode_radio_source = wx.RadioButton(mode_panel, label="By Source", style=wx.RB_GROUP)
        self.mode_radio_source.SetMinSize((120, -1))  # Minimum width to prevent size issues
        self.mode_radio_all = wx.RadioButton(mode_panel, label="All News (Latest First)")
        self.mode_radio_all.SetMinSize((180, -1))  # Minimum width to prevent size issues
        
        self.mode_radio_source.SetValue(True)  # Default to source mode
        
        mode_sizer.Add(self.mode_radio_source, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        mode_sizer.Add(self.mode_radio_all, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        mode_sizer.AddStretchSpacer(1)  # Push everything to the left
        
        mode_panel.SetSizer(mode_sizer)
        mode_sizer.Fit(mode_panel)  # Fit the sizer to contents
        main_sizer.Add(mode_panel, 0, wx.EXPAND | wx.ALL, 0)
        
        # === CONTENT PANEL (sources list + news list) ===
        content_panel = wx.Panel(self)
        content_panel.SetBackgroundColour("gray")
        
        self.sources_list = wx.ListCtrl(
            content_panel, 
            style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        self.sources_list.InsertColumn(0, "Source", width=200)
        
        # Don't call getNewsSources() - load from database instead
        # self.getNewsSources()
        
        self.news_list = wx.ListCtrl(
            content_panel, 
            size = (-1 , - 1),
            style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        self.news_list.InsertColumn(0, 'URL', width=250)
        self.news_list.InsertColumn(1, 'Title', width=400)
        self.news_list.InsertColumn(2, 'Article ID', width=100)
        self.news_list.InsertColumn(3, 'Source', width=150)
        self.news_list.InsertColumn(4, 'Published', width=150)
        
        content_sizer = wx.BoxSizer(wx.HORIZONTAL)
        content_sizer.Add(self.sources_list, 0, wx.ALL | wx.EXPAND)
        content_sizer.Add(self.news_list, 1, wx.ALL | wx.EXPAND)
        content_panel.SetSizer(content_sizer)
        
        main_sizer.Add(content_panel, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

#        self.sources = self.getNewsSources()
        self.url_queue = Queue()
  
        # Bind events
        self.sources_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnSourceSelected)
        self.news_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnLinkSelected)  # Double-click to open details
        self.mode_radio_source.Bind(wx.EVT_RADIOBUTTON, self.OnModeChange)
        self.mode_radio_all.Bind(wx.EVT_RADIOBUTTON, self.OnModeChange)
        
        # EVT_PAINT binding removed - column resizing now done in OnSourceSelected
        
        
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
                # Convert bytes to string if necessary for consistent key format
                if isinstance(article_key, bytes):
                    article_key = article_key.decode('utf-8')
                elif not isinstance(article_key, str):
                    article_key = str(article_key)
                    
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
        
    def OnModeChange(self, event):
        """Handle mode change between 'By Source' and 'All News'"""
        if self.mode_radio_source.GetValue():
            new_mode = 'source'
        else:
            new_mode = 'all'
        
        if new_mode != self.view_mode:
            self.view_mode = new_mode
            print(f"\nMode changed to: {self.view_mode}")
            
            # Clear news list
            self.news_list.DeleteAllItems()
            
            if self.view_mode == 'all':
                # Check if sources are loaded
                if not self.sources or len(self.sources) == 0:
                    print("⚠️  Sources not loaded yet. Please wait for sources to load first.")
                    # Show a message to user
                    wx.MessageBox(
                        "Sources are still loading. Please wait a moment and try again.",
                        "Loading...",
                        wx.OK | wx.ICON_INFORMATION
                    )
                    # Switch back to source mode
                    self.mode_radio_source.SetValue(True)
                    self.view_mode = 'source'
                    return
                
                # Load all news
                self.LoadAllNews()
                print(f"✓ Loaded {self.news_list.GetItemCount()} articles in All News mode")
            else:
                # Back to source mode - clear selection
                print("Switched to Source mode - select a source to view articles")
    
    def OnSourceSelected(self, event):
         # Only handle source selection in 'source' mode
         if self.view_mode != 'source':
             return
         
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
         
         self.populating_list = True  # Set flag before populating
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
                    url = source_articles[key]["url"] if source_articles[key]["url"] else ""
                    # Clean up title: strip whitespace, replace multiple spaces, provide fallback
                    title = source_articles[key]["title"] if source_articles[key]["title"] else ""
                    if title:
                        title = ' '.join(title.split())  # Strip and normalize whitespace
                    if not title or len(title.strip()) == 0:
                        title = "(No Title)"
                    published = source_articles[key]["publishedAt"] if source_articles[key]["publishedAt"] else "N/A"
                    
                    # Use InsertStringItem for LC_REPORT mode
                    actual_index = self.news_list.InsertItem(self.news_list.GetItemCount(), url)
                    if actual_index == -1:
                        print(f"ERROR: InsertItem failed for article {index}")
                        continue
                    
                    # Set remaining columns
                    self.news_list.SetItem(actual_index, 1, title)
                    self.news_list.SetItem(actual_index, 2, key)  # key is already a string
                    self.news_list.SetItem(actual_index, 3, source_name)  # Source name
                    self.news_list.SetItem(actual_index, 4, published)  # Published date
                    
                    index += 1
                    
                    # Force update every 50 items to show progress
                    if index % 50 == 0:
                        self.news_list.Update()
                        wx.SafeYield()
                
                print(f'✓ Inserted {index} articles into news_list')
                print(f'DEBUG: List item count after insertion: {self.news_list.GetItemCount()}')
                break  # Exit loop after finding match
         
         if not found:
             print(f'✗ NO MATCH FOUND for: "{source}"')
         
         # Force immediate update before any other processing
         self.news_list.Update()
         
         # Force column resize to ensure they're visible
         width, height = self.news_list.GetSize()
         if width > 0:
             self.news_list.SetColumnWidth(0, 250)
             self.news_list.SetColumnWidth(1, max(400, int(width * 0.5)))
             self.news_list.SetColumnWidth(2, 100)
             self.news_list.SetColumnWidth(3, 150)
             self.news_list.SetColumnWidth(4, 150)
             print(f"DEBUG: Resized columns to fixed widths, list size: {width}x{height}")
         
         # Refresh the list to ensure items are displayed
         self.news_list.Refresh()
         
         # Use CallAfter to clear flag after all pending events are processed
         wx.CallAfter(self._clear_populating_flag)
         print('='*50 + '\n')
    
    def _clear_populating_flag(self):
        """Clear the populating flag after a short delay"""
        self.populating_list = False
        item_count = self.news_list.GetItemCount()
        print(f"DEBUG: populating_list flag cleared, final item count: {item_count}")
        
        # Force layout update on the panel
        self.Layout()
        
        # Force update of the list control
        self.news_list.Update()
        self.news_list.Refresh()
        
        # Force parent to update as well
        parent = self.GetParent()
        if parent:
            parent.Layout()
            parent.Refresh()
        
        # Try to select first item to make it visible
        if item_count > 0:
            self.news_list.EnsureVisible(0)
            print(f"DEBUG: Made first item visible")
            
            # Check if list is actually shown and has size
            print(f"DEBUG: news_list.IsShown() = {self.news_list.IsShown()}")
            print(f"DEBUG: news_list.GetSize() = {self.news_list.GetSize()}")
            
            # Print first few items to verify they're actually there
            for i in range(min(3, item_count)):
                title = self.news_list.GetItem(i, 1).GetText()
                url = self.news_list.GetItem(i, 0).GetText()
                key = self.news_list.GetItem(i, 2).GetText()
                print(f"DEBUG: Item {i}: key='{key}' | {title[:50]}... | URL: {url[:40]}...")
         
    
    def LoadAllNews(self):
        """Load all articles from all sources, sorted by date (newest first)"""
        print("\nLoading all news articles...")
        
        # Freeze the window to prevent flickering during update
        self.Freeze()
        
        try:
            # Collect all articles from all sources
            all_articles = []
            
            for source_key, source in self.sources.items():
                source_name = source.get('name', 'Unknown')
                articles = source.get('articles', {})
                
                for article_key, article in articles.items():
                    # Add source info to each article
                    article_with_source = article.copy()
                    article_with_source['source_name'] = source_name
                    article_with_source['source_key'] = source_key
                    all_articles.append(article_with_source)
            
            print(f"Collected {len(all_articles)} articles from {len(self.sources)} sources")
            
            if len(all_articles) == 0:
                print("⚠️  No articles found!")
                wx.MessageBox(
                    "No articles available to display. Please wait for the news to load.",
                    "No Articles",
                    wx.OK | wx.ICON_WARNING
                )
                return
            
            # Sort by publishedAt (newest first)
            # Parse dates for sorting
            def get_date(article):
                try:
                    date_str = article.get('publishedAt', '')
                    if date_str:
                        # Try to parse the date
                        parsed_date = date_parser.parse(date_str)
                        # Remove timezone info to avoid comparison issues
                        if parsed_date.tzinfo is not None:
                            parsed_date = parsed_date.replace(tzinfo=None)
                        return parsed_date
                    return datetime.min
                except Exception as e:
                    # If parsing fails, return minimum date
                    return datetime.min
            
            all_articles.sort(key=get_date, reverse=True)
            
            print(f"Sorted articles by date, displaying in news list...")
            
            # Display in news_list
            self.populating_list = True
            self.news_list.DeleteAllItems()
            
            for index, article in enumerate(all_articles):
                url = article.get('url', '')
                # Clean up title: strip whitespace, replace multiple spaces, provide fallback
                title = article.get('title', '')
                if title:
                    title = ' '.join(title.split())  # Strip and normalize whitespace
                if not title or len(title.strip()) == 0:
                    title = "(No Title)"
                article_key = article.get('id_article', '')
                source_name = article.get('source_name', 'Unknown')
                published = article.get('publishedAt', 'N/A')
                
                # Convert bytes to string if needed
                if isinstance(article_key, bytes):
                    article_key = article_key.decode('utf-8')
                elif not isinstance(article_key, str):
                    article_key = str(article_key)
                
                # Insert item
                actual_index = self.news_list.InsertItem(self.news_list.GetItemCount(), url)
                if actual_index != -1:
                    self.news_list.SetItem(actual_index, 1, title)
                    self.news_list.SetItem(actual_index, 2, article_key)
                    self.news_list.SetItem(actual_index, 3, source_name)
                    self.news_list.SetItem(actual_index, 4, published)
                
                # Log progress (but don't yield during update)
                if index % 500 == 0 and index > 0:
                    print(f"  Loaded {index} articles...")
            
            # Force column resize
            width, height = self.news_list.GetSize()
            if width > 0:
                self.news_list.SetColumnWidth(0, 200)  # URL narrower
                self.news_list.SetColumnWidth(1, max(450, int(width * 0.4)))  # Title wider
                self.news_list.SetColumnWidth(2, 100)  # Article ID
                self.news_list.SetColumnWidth(3, 180)  # Source
                self.news_list.SetColumnWidth(4, 150)  # Published
            
            print(f"✓ Loaded {len(all_articles)} articles in All News mode\n")
            
        finally:
            # Always thaw, even if error occurs
            self.Thaw()
            
            # Clear populating flag and refresh display
            self.populating_list = False
            self.news_list.Update()
            self.news_list.Refresh()
            self.Layout()
    
    def OnLinkSelected(self, event):
        """Open article detail frame when article is double-clicked"""
        print(f"DEBUG: OnLinkSelected fired (double-click) in {self.view_mode} mode")
        
        # Get selected item index
        selected_index = event.GetIndex()
        
        # Get article key from column 2
        article_key = self.news_list.GetItem(selected_index, 2).GetText()
        print(f"DEBUG: Retrieved article_key from list: '{article_key}' (type: {type(article_key)})")
        
        article_data = None
        source_name = 'Unknown Source'
        
        if self.view_mode == 'all':
            # In "All News" mode, search through all sources
            source_name = self.news_list.GetItem(selected_index, 3).GetText()
            for source_key, source in self.sources.items():
                if article_key in source['articles']:
                    article_data = source['articles'][article_key]
                    source_name = source.get('name', source_name)
                    print(f"DEBUG: Found article in source: {source_name}")
                    break
        else:
            # In "By Source" mode, use current selected source
            if hasattr(self, 'current_source_key') and self.current_source_key:
                source = self.sources.get(self.current_source_key)
                if source:
                    print(f"DEBUG: Available article keys in source: {list(source['articles'].keys())[:5]}...")
                    article_data = source['articles'].get(article_key)
                    source_name = source.get('name', 'Unknown Source')
                else:
                    print(f"Source {self.current_source_key} not found")
        
        if article_data:
            print(f"DEBUG: Found article, opening detail frame")
            detail_frame = ArticleDetailFrame(self, article_data, source_name)
            detail_frame.Show()
        else:
            print(f"ERROR: Article '{article_key}' not found")
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
