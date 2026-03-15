#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wxAsyncNewsReader v6 - Modern interface with Notebook and CheckListBox

@author: jamaj
"""

from __future__ import print_function

import logging
import sys
import wx 
import wx.html2
import webbrowser
from datetime import datetime

from wxasync import WxAsyncApp
from asyncio.events import get_event_loop
import os

from sqlalchemy import (create_engine, Table, Column, Integer, 
    String, MetaData, Text, select, func)

# Load credentials from environment
from decouple import config


def dbCredentials():
    """Return SQLite database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path


def dbOpen():    
    """Open database connection with SQLAlchemy"""
    db_path = dbCredentials()
    eng = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False},
        pool_pre_ping=True
    )
    return eng


class NewsPanel(wx.Panel):
    """Main panel with checkbox source list and notebook with HTML viewer"""

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.SetBackgroundColour("white")
        
        # Data structures
        self.sources = {}
        self.source_id_map = {}  # Map checkbox index to source_id
        
        # Create main horizontal sizer (sidebar + content)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # === LEFT SIDEBAR: Source CheckList ===
        sidebar_panel = wx.Panel(self)
        sidebar_panel.SetBackgroundColour(wx.Colour(245, 245, 245))
        sidebar_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Title
        title = wx.StaticText(sidebar_panel, label="News Sources")
        title_font = title.GetFont()
        title_font.PointSize += 2
        title_font = title_font.Bold()
        title.SetFont(title_font)
        sidebar_sizer.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        # Button panel for Select All / Deselect All / Load Checked
        button_panel = wx.Panel(sidebar_panel)
        button_panel.SetBackgroundColour(wx.Colour(245, 245, 245))
        button_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # First row: Select/Deselect
        row1_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.select_all_btn = wx.Button(button_panel, label="Select All", size=(90, 28))
        self.deselect_all_btn = wx.Button(button_panel, label="Deselect All", size=(90, 28))
        row1_sizer.Add(self.select_all_btn, 0, wx.RIGHT, 5)
        row1_sizer.Add(self.deselect_all_btn, 0)
        button_sizer.Add(row1_sizer, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        # Second row: Load Checked button
        self.load_checked_btn = wx.Button(button_panel, label="📰 Load Checked", size=(190, 32))
        self.load_checked_btn.SetBackgroundColour(wx.Colour(102, 126, 234))
        self.load_checked_btn.SetForegroundColour(wx.WHITE)
        button_sizer.Add(self.load_checked_btn, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        button_panel.SetSizer(button_sizer)
        sidebar_sizer.Add(button_panel, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        # CheckListBox for sources
        self.sources_checklist = wx.CheckListBox(
            sidebar_panel, 
            style=wx.LB_SINGLE | wx.LB_HSCROLL
        )
        sidebar_sizer.Add(self.sources_checklist, 1, wx.ALL | wx.EXPAND, 10)
        
        # Status text
        self.status_text = wx.StaticText(sidebar_panel, label="Loading sources...")
        self.status_text.SetForegroundColour(wx.Colour(100, 100, 100))
        sidebar_sizer.Add(self.status_text, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        sidebar_panel.SetSizer(sidebar_sizer)
        main_sizer.Add(sidebar_panel, 0, wx.EXPAND | wx.ALL, 0)
        main_sizer.SetItemMinSize(sidebar_panel, 280, -1)
        
        # === RIGHT SIDE: Notebook with tabs ===
        self.notebook = wx.Notebook(self, style=wx.NB_TOP)
        
        # Tab 1: HTML Viewer
        html_panel = wx.Panel(self.notebook)
        html_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # HTML Viewer
        self.html_viewer = wx.html2.WebView.New(html_panel)
        html_sizer.Add(self.html_viewer, 1, wx.EXPAND | wx.ALL, 5)
        
        html_panel.SetSizer(html_sizer)
        self.notebook.AddPage(html_panel, "News Viewer")
        
        main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 0)
        
        self.SetSizer(main_sizer)
        
        # Bind events
        self.select_all_btn.Bind(wx.EVT_BUTTON, self.OnSelectAll)
        self.deselect_all_btn.Bind(wx.EVT_BUTTON, self.OnDeselectAll)
        self.load_checked_btn.Bind(wx.EVT_BUTTON, self.OnLoadChecked)
        self.sources_checklist.Bind(wx.EVT_CHECKLISTBOX, self.OnSourceChecked)
        self.sources_checklist.Bind(wx.EVT_LISTBOX, self.OnSourceSelected)
        
        # Load data
        wx.CallAfter(self.LoadSources)
        
        # Auto-refresh every 60 seconds
        wx.CallLater(60000, self.RefreshNews)
    
    def LoadSources(self):
        """Load sources from database and populate CheckListBox"""
        print("\n=== Loading Sources ===")
        
        try:
            eng = dbOpen()
            meta = MetaData()
            
            gm_sources = Table('gm_sources', meta, autoload_with=eng)
            gm_articles = Table('gm_articles', meta, autoload_with=eng)
            
            con = eng.connect()
            
            # Get sources with article counts
            MIN_ARTICLES = 10
            
            stm = select(gm_sources)
            rs = con.execute(stm)
            
            source_list = []
            for source in rs.fetchall():
                source_id = source[0]
                source_name = source[1] if source[1] else ""
                
                # Count articles
                stm_count = select(func.count()).select_from(gm_articles).where(
                    gm_articles.c.id_source == source_id
                )
                article_count = con.execute(stm_count).scalar() or 0
                
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
            
            print(f"Found {len(source_list)} sources with >= {MIN_ARTICLES} articles")
            
            # Populate CheckListBox
            self.sources_checklist.Clear()
            self.source_id_map = {}
            
            for idx, item in enumerate(source_list):
                source_id = item['source_id']
                source_name = item['source_name']
                article_count = item['article_count']
                
                display_name = f"{source_name} ({article_count})"
                self.sources_checklist.Append(display_name)
                self.source_id_map[idx] = source_id
                
                # Store full source data
                self.sources[source_id] = {
                    'id_source': source_id,
                    'name': source_name,
                    'description': item['source_data'][2],
                    'url': item['source_data'][3],
                    'category': item['source_data'][4],
                    'language': item['source_data'][5],
                    'country': item['source_data'][6],
                    'article_count': article_count
                }
            
            con.close()
            
            # Update status
            self.status_text.SetLabel(f"{len(source_list)} sources loaded")
            
            # Select all sources by default
            for i in range(self.sources_checklist.GetCount()):
                self.sources_checklist.Check(i, True)
            
            checked_count = self.sources_checklist.GetCount()
            self.status_text.SetLabel(f"{checked_count} sources selected")
            print(f"✓ Auto-selected all {checked_count} sources")
            
            # Auto-load checked sources
            wx.CallAfter(self.LoadCheckedSources)
            
            print(f"✓ Loaded {len(source_list)} sources")
            
        except Exception as e:
            print(f"ERROR loading sources: {e}")
            import traceback
            traceback.print_exc()
            self.status_text.SetLabel("Error loading sources")
    
    def ShowWelcomeMessage(self):
        """Display welcome message in HTML viewer"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    padding: 40px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    margin: 0;
                }
                .container {
                    max-width: 800px;
                    margin: 0 auto;
                    background: rgba(255, 255, 255, 0.1);
                    backdrop-filter: blur(10px);
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
                }
                h1 {
                    font-size: 48px;
                    margin: 0 0 20px 0;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                }
                .subtitle {
                    font-size: 20px;
                    margin-bottom: 30px;
                    opacity: 0.9;
                }
                .instruction {
                    background: rgba(255, 255, 255, 0.2);
                    padding: 20px;
                    border-radius: 10px;
                    margin: 20px 0;
                    font-size: 16px;
                    line-height: 1.6;
                }
                .step {
                    margin: 15px 0;
                    padding-left: 30px;
                    position: relative;
                }
                .step:before {
                    content: "▶";
                    position: absolute;
                    left: 0;
                    color: #ffd700;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📰 News Reader v6</h1>
                <div class="subtitle">Modern interface with source filtering</div>
                
                <div class="instruction">
                    <strong>How to use:</strong>
                    <div class="step">Select news sources from the list on the left</div>
                    <div class="step">Check/uncheck sources to filter articles</div>
                    <div class="step">Use "Select All" or "Deselect All" buttons</div>
                    <div class="step">Click on a source to view its articles</div>
                </div>
                
                <div class="instruction">
                    <strong>Features:</strong>
                    <div class="step">Modern tabbed interface with wx.Notebook</div>
                    <div class="step">CheckListBox for easy source management</div>
                    <div class="step">HTML5 viewer with wx.html2.WebView</div>
                    <div class="step">Auto-refresh every 60 seconds</div>
                </div>
            </div>
        </body>
        </html>
        """
        self.html_viewer.SetPage(html, "")
    
    def OnSelectAll(self, event):
        """Select all sources in CheckListBox"""
        for i in range(self.sources_checklist.GetCount()):
            self.sources_checklist.Check(i, True)
        
        checked_count = sum(1 for i in range(self.sources_checklist.GetCount()) 
                          if self.sources_checklist.IsChecked(i))
        self.status_text.SetLabel(f"{checked_count} sources selected")
        print(f"Selected all {checked_count} sources")
    
    def OnDeselectAll(self, event):
        """Deselect all sources in CheckListBox"""
        for i in range(self.sources_checklist.GetCount()):
            self.sources_checklist.Check(i, False)
        
        self.status_text.SetLabel("0 sources selected")
        print("Deselected all sources")
    
    def OnSourceChecked(self, event):
        """Handle checkbox state change"""
        index = event.GetInt()
        is_checked = self.sources_checklist.IsChecked(index)
        source_id = self.source_id_map.get(index)
        
        if source_id:
            source_name = self.sources[source_id]['name']
            state = "checked" if is_checked else "unchecked"
            print(f"Source {state}: {source_name}")
        
        # Update status
        checked_count = sum(1 for i in range(self.sources_checklist.GetCount()) 
                          if self.sources_checklist.IsChecked(i))
        self.status_text.SetLabel(f"{checked_count} sources selected")
        
        # Auto-load checked sources if any are checked
        if checked_count > 0:
            wx.CallAfter(self.LoadCheckedSources)
    
    def OnSourceSelected(self, event):
        """Handle source selection (single click)"""
        index = event.GetInt()
        source_id = self.source_id_map.get(index)
        
        if source_id and source_id in self.sources:
            source = self.sources[source_id]
            self.LoadSourceArticles(source_id)
    
    def OnLoadChecked(self, event):
        """Load articles from all checked sources"""
        self.LoadCheckedSources()
    
    def LoadCheckedSources(self):
        """Load articles from all checked sources combined"""
        # Get checked source IDs
        checked_source_ids = []
        for i in range(self.sources_checklist.GetCount()):
            if self.sources_checklist.IsChecked(i):
                source_id = self.source_id_map.get(i)
                if source_id:
                    checked_source_ids.append(source_id)
        
        if not checked_source_ids:
            self.ShowWelcomeMessage()
            return
        
        print(f"\n=== Loading articles from {len(checked_source_ids)} checked sources ===")
        
        try:
            eng = dbOpen()
            meta = MetaData()
            gm_articles = Table('gm_articles', meta, autoload_with=eng)
            
            con = eng.connect()
            
            # Load articles from all checked sources
            stm = select(gm_articles).where(
                gm_articles.c.id_source.in_(checked_source_ids)
            ).order_by(gm_articles.c.published_at_gmt.desc().nullslast()).limit(200)
            
            articles = con.execute(stm).fetchall()
            con.close()
            
            if not articles:
                source_names = [self.sources[sid]['name'] for sid in checked_source_ids[:3]]
                display_names = ", ".join(source_names)
                if len(checked_source_ids) > 3:
                    display_names += f" and {len(checked_source_ids) - 3} more"
                self.ShowNoArticlesMessage(display_names)
                return
            
            # Build HTML with multiple sources
            source_names = [self.sources[sid]['name'] for sid in checked_source_ids]
            html = self.BuildMultiSourceArticlesHTML(source_names, articles)
            self.html_viewer.SetPage(html, "")
            
            print(f"✓ Loaded {len(articles)} articles from {len(checked_source_ids)} sources")
            
        except Exception as e:
            print(f"ERROR loading articles: {e}")
            import traceback
            traceback.print_exc()
    
    def LoadSourceArticles(self, source_id):
        """Load and display articles from selected source"""
        print(f"\n=== Loading articles for source: {source_id} ===")
        
        try:
            source = self.sources.get(source_id)
            if not source:
                print(f"ERROR: Source {source_id} not found")
                return
            
            eng = dbOpen()
            meta = MetaData()
            gm_articles = Table('gm_articles', meta, autoload_with=eng)
            
            con = eng.connect()
            
            # Load articles for this source, prefer published_at_gmt
            stm = select(gm_articles).where(
                gm_articles.c.id_source == source_id
            ).order_by(gm_articles.c.published_at_gmt.desc().nullslast()).limit(50)
            
            articles = con.execute(stm).fetchall()
            con.close()
            
            if not articles:
                self.ShowNoArticlesMessage(source['name'])
                return
            
            # Build HTML to display articles
            html = self.BuildArticlesHTML(source, articles)
            self.html_viewer.SetPage(html, "")
            
            print(f"✓ Loaded {len(articles)} articles")
            
        except Exception as e:
            print(f"ERROR loading articles: {e}")
            import traceback
            traceback.print_exc()
    
    def ShowNoArticlesMessage(self, source_name):
        """Display message when no articles found"""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    padding: 40px;
                    text-align: center;
                    color: #666;
                }}
                h2 {{ color: #999; }}
            </style>
        </head>
        <body>
            <h2>📭 No Articles Found</h2>
            <p>No articles available for <strong>{source_name}</strong></p>
        </body>
        </html>
        """
        self.html_viewer.SetPage(html, "")
    
    def BuildMultiSourceArticlesHTML(self, source_names, articles):
        """Build HTML page with articles from multiple sources combined"""
        article_count = len(articles)
        source_count = len(source_names)
        
        # Show first few source names
        if source_count <= 3:
            subtitle = f"From: {', '.join(source_names)}"
        else:
            subtitle = f"From: {', '.join(source_names[:3])} and {source_count - 3} more"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background: #f5f5f5;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 10px;
                    margin-bottom: 20px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                .header h1 {{
                    margin: 0 0 10px 0;
                    font-size: 32px;
                }}
                .header .subtitle {{
                    opacity: 0.9;
                    font-size: 16px;
                }}
                .article {{
                    background: white;
                    padding: 20px;
                    margin-bottom: 15px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    transition: transform 0.2s, box-shadow 0.2s;
                }}
                .article:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
                }}
                .article-title {{
                    font-size: 20px;
                    font-weight: bold;
                    color: #333;
                    margin-bottom: 10px;
                }}
                .article-title a {{
                    color: #667eea;
                    text-decoration: none;
                }}
                .article-title a:hover {{
                    text-decoration: underline;
                }}
                .article-meta {{
                    color: #666;
                    font-size: 14px;
                    margin-bottom: 10px;
                }}
                .article-meta span {{
                    margin-right: 15px;
                }}
                .article-description {{
                    color: #555;
                    line-height: 1.6;
                    margin-top: 10px;
                }}
                .article-content {{
                    margin-top: 10px;
                    clear: both;
                    display: block;
                    width: 100%;
                }}
                .article-content img {{
                    max-width: 100%;
                    width: 100%;
                    height: auto;
                    border-radius: 4px;
                    margin: 10px 0;
                    display: block;
                    float: none !important;
                    clear: both;
                }}
                .article-source {{
                    color: #667eea;
                    font-weight: 600;
                }}
                .article-author {{
                    color: #764ba2;
                    font-weight: 500;
                }}
                .article-date {{
                    color: #999;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📰 Combined News Feed</h1>
                <div class="subtitle">{article_count} articles from {source_count} sources</div>
                <div class="subtitle" style="margin-top: 5px; font-size: 14px;">{subtitle}</div>
            </div>
        """
        
        for article in articles:
            article_id = article[0]
            source_id = article[1] if article[1] else "unknown"
            author = article[2] if article[2] and article[2].strip() else None
            title = article[3] if article[3] and article[3].strip() else "Untitled Article"
            description = article[4] if article[4] and article[4].strip() else None
            url = article[5] if article[5] and article[5].strip() else "#"
            url_to_image = article[6] if len(article) > 6 and article[6] and article[6].strip() else None
            published_at = article[7] if article[7] else None
            published_at_gmt = article[9] if len(article) > 9 and article[9] else None
            
            # Get source name
            source_name = self.sources.get(source_id, {}).get('name', source_id)
            
            # Format date - prefer GMT time
            date_str = None
            if published_at_gmt:
                try:
                    dt = datetime.fromisoformat(published_at_gmt.replace('Z', '+00:00'))
                    date_str = dt.strftime('%Y-%m-%d %H:%M GMT')
                except:
                    pass
            
            if not date_str and published_at:
                try:
                    dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                    date_str = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    date_str = published_at
            
            if not date_str:
                date_str = "Date unknown"
            
            # Escape HTML for title, author, and source name
            title = title.replace('<', '&lt;').replace('>', '&gt;').replace('\"', '&quot;')
            if author:
                author = author.replace('<', '&lt;').replace('>', '&gt;')
            source_name = source_name.replace('<', '&lt;').replace('>', '&gt;')
            
            # Check if description contains HTML
            description_is_html = False
            if description:
                description_is_html = '<' in description and '>' in description
                if not description_is_html:
                    # Only escape if not HTML
                    description = description.replace('<', '&lt;').replace('>', '&gt;')
            
            # Build article card
            article_html = f"""
            <div class="article">
                <div class="article-title">
                    <a href="{url}" target="_blank">{title}</a>
                </div>
                <div class="article-meta">
                    <span class="article-source">🔖 {source_name}</span>
                    {f'<span class="article-author">✍️ {author}</span>' if author else ''}
                    <span class="article-date">📅 {date_str}</span>
                </div>
            """
            
            # Add image and description directly (no nested divs)
            if url_to_image:
                article_html += f'<img src="{url_to_image}" alt="Article image" style="max-width: 100%; width: 100%; height: auto; display: block; margin: 10px 0; border-radius: 4px; clear: both;">'
            
            if description:
                article_html += f'<div class="article-description">{description}</div>'
            
            article_html += '</div>'
            html += article_html
        
        html += """
        </body>
        </html>
        """
        
        return html
    
    def BuildArticlesHTML(self, source, articles):
        """Build HTML page with article list from single source"""
        source_name = source['name']
        article_count = len(articles)
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background: #f5f5f5;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 10px;
                    margin-bottom: 20px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                .header h1 {{
                    margin: 0 0 10px 0;
                    font-size: 32px;
                }}
                .header .subtitle {{
                    opacity: 0.9;
                    font-size: 16px;
                }}
                .article {{
                    background: white;
                    padding: 20px;
                    margin-bottom: 15px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    transition: transform 0.2s, box-shadow 0.2s;
                }}
                .article:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
                }}
                .article-title {{
                    font-size: 20px;
                    font-weight: bold;
                    color: #333;
                    margin-bottom: 10px;
                }}
                .article-title a {{
                    color: #667eea;
                    text-decoration: none;
                }}
                .article-title a:hover {{
                    text-decoration: underline;
                }}
                .article-meta {{
                    color: #666;
                    font-size: 14px;
                    margin-bottom: 10px;
                }}
                .article-meta span {{
                    margin-right: 15px;
                }}
                .article-description {{
                    color: #555;
                    line-height: 1.6;
                    margin-top: 10px;
                    clear: both;
                }}
                .article-content {{
                    margin-top: 10px;
                    clear: both;
                    display: block;
                    width: 100%;
                }}
                .article-content img {{
                    max-width: 100%;
                    width: 100%;
                    height: auto;
                    border-radius: 4px;
                    margin: 10px 0;
                    display: block;
                    float: none !important;
                    clear: both;
                }}
                .article-author {{
                    color: #764ba2;
                    font-weight: 500;
                }}
                .article-date {{
                    color: #999;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📰 {source_name}</h1>
                <div class="subtitle">{article_count} recent articles</div>
            </div>
        """
        
        for article in articles:
            article_id = article[0]
            author = article[2] if article[2] and article[2].strip() else None
            title = article[3] if article[3] and article[3].strip() else "Untitled Article"
            description = article[4] if article[4] and article[4].strip() else None
            url = article[5] if article[5] and article[5].strip() else "#"
            url_to_image = article[6] if len(article) > 6 and article[6] and article[6].strip() else None
            published_at = article[7] if article[7] else None
            published_at_gmt = article[9] if len(article) > 9 and article[9] else None
            
            # Format date - prefer GMT time
            date_str = None
            if published_at_gmt:
                try:
                    dt = datetime.fromisoformat(published_at_gmt.replace('Z', '+00:00'))
                    date_str = dt.strftime('%Y-%m-%d %H:%M GMT')
                except:
                    pass
            
            if not date_str and published_at:
                try:
                    dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                    date_str = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    date_str = published_at
            
            if not date_str:
                date_str = "Date unknown"
            
            # Escape HTML for title and author
            title = title.replace('<', '&lt;').replace('>', '&gt;').replace('\"', '&quot;')
            if author:
                author = author.replace('<', '&lt;').replace('>', '&gt;')
            
            # Check if description contains HTML
            description_is_html = False
            if description:
                description_is_html = '<' in description and '>' in description
                if not description_is_html:
                    # Only escape if not HTML
                    description = description.replace('<', '&lt;').replace('>', '&gt;')
            
            # Build article card
            article_html = f"""
            <div class="article">
                <div class="article-title">
                    <a href="{url}" target="_blank">{title}</a>
                </div>
                <div class="article-meta">
                    {f'<span class="article-author">✍️ {author}</span>' if author else ''}
                    <span class="article-date">📅 {date_str}</span>
                </div>
            """
            
            # Add image and description directly (no nested divs)
            if url_to_image:
                article_html += f'<img src="{url_to_image}" alt="Article image" style="max-width: 100%; width: 100%; height: auto; display: block; margin: 10px 0; border-radius: 4px; clear: both;">'
            
            if description:
                article_html += f'<div class="article-description">{description}</div>'
            
            article_html += '</div>'
            html += article_html
        
        html += """
        </body>
        </html>
        """
        
        return html
    
    def RefreshNews(self):
        """Auto-refresh news sources"""
        print("\n🔄 Auto-refreshing news...")
        self.LoadSources()
        wx.CallLater(60000, self.RefreshNews)


class MainWindow(wx.Frame):
    """Main application window"""
    
    def __init__(self, parent, title):
        super(MainWindow, self).__init__(
            parent, 
            title=title, 
            size=(1400, 900)
        )
        self.Centre()
        
        # Create news panel
        NewsPanel(self)
        
        # Status bar
        self.CreateStatusBar()
        self.SetStatusText("Ready")
        
        # Create menu
        self.createMenu()
    
    def createMenu(self):
        """Create menu bar"""
        menu = wx.Menu()
        menuExit = menu.Append(wx.ID_EXIT, "E&xit\tCtrl+Q", "Quit application")
        
        menuBar = wx.MenuBar()
        menuBar.Append(menu, "&File")
        self.SetMenuBar(menuBar)
        
        self.Bind(wx.EVT_MENU, self.OnExit, menuExit)
    
    def OnExit(self, event):
        """Exit application"""
        self.Close(True)


class NewsGatherApp(WxAsyncApp):
    """Main application class"""
    
    def OnInit(self):
        """Initialize application"""
        window = MainWindow(None, "📰 News Reader v6 - Modern Interface")
        window.Show()
        self.SetTopWindow(window)
        return True


if __name__ == '__main__':
    # Setup logging
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)
    
    # Run application
    print("=" * 60)
    print("Starting News Reader v6")
    print("=" * 60)
    
    app = NewsGatherApp(False)
    loop = get_event_loop()
    loop.run_until_complete(app.MainLoop())
