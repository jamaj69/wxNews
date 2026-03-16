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
import wx.lib.agw.aui as aui
import webbrowser
import re
import html
from html.parser import HTMLParser
from datetime import datetime
import requests
import json
import time
from threading import Thread

from wxasync import WxAsyncApp
from asyncio.events import get_event_loop
import os

from sqlalchemy import (create_engine, Table, Column, Integer, 
    String, MetaData, Text, select, func)

# Load credentials from environment
from decouple import config

# API Configuration
API_URL = config('NEWS_API_URL', default='http://localhost:8765')
POLL_INTERVAL_MS = int(config('NEWS_POLL_INTERVAL_MS', default=30000))  # 30 seconds


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


class NewsAPIClient:
    """Client for polling new articles from FastAPI server"""
    
    def __init__(self, api_url=API_URL):
        self.api_url = api_url
        self.last_timestamp = 0
        self.enabled = False
        
    def get_initial_timestamp(self):
        """Get initial sync point from API"""
        try:
            response = requests.get(
                f"{self.api_url}/api/latest_timestamp",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                self.last_timestamp = data.get('latest_timestamp', 0)
                self.enabled = True
                return self.last_timestamp
        except Exception as e:
            logging.warning(f"Failed to get initial timestamp: {e}")
            self.enabled = False
        return 0
    
    def poll_new_articles(self, source_ids=None, limit=50):
        """Poll for new articles since last check"""
        if not self.enabled or self.last_timestamp == 0:
            return []
        
        try:
            params = {
                'since': self.last_timestamp,
                'limit': limit
            }
            
            if source_ids:
                params['sources'] = ','.join(source_ids)
            
            response = requests.get(
                f"{self.api_url}/api/articles",
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    # Update last timestamp
                    self.last_timestamp = data.get('latest_timestamp', self.last_timestamp)
                    return data.get('articles', [])
        except Exception as e:
            logging.warning(f"Failed to poll new articles: {e}")
        
        return []
    
    def is_enabled(self):
        """Check if API polling is enabled"""
        return self.enabled


class HTMLContentExtractor(HTMLParser):
    """Parse HTML descriptions from RSS feeds and extract text and images"""
    
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.images = []
        self.in_script = False
        self.in_style = False
        
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.in_script = True
        elif tag == 'style':
            self.in_style = True
        elif tag == 'img':
            # Extract image src
            for attr_name, attr_value in attrs:
                if attr_name == 'src' and attr_value:
                    self.images.append(attr_value)
        elif tag == 'br':
            self.text_parts.append(' ')
        elif tag in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # Add space before block elements
            if self.text_parts and self.text_parts[-1] != ' ':
                self.text_parts.append(' ')
    
    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False
        elif tag == 'style':
            self.in_style = False
        elif tag in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # Add space after block elements
            if self.text_parts and self.text_parts[-1] != ' ':
                self.text_parts.append(' ')
    
    def handle_data(self, data):
        if not self.in_script and not self.in_style:
            # Add text content
            text = data.strip()
            if text:
                self.text_parts.append(text)
    
    def get_content(self):
        """Return extracted text and images"""
        # Join text parts and clean up whitespace
        text = ' '.join(self.text_parts)
        text = re.sub(r'\s+', ' ', text).strip()
        return text, self.images


def parse_html_description(html_content):
    """Parse HTML description and extract text and images"""
    if not html_content:
        return "", []
    
    # IMPORTANT: Unescape HTML entities first (in case description is stored escaped in DB)
    # This converts &lt; back to <, &gt; to >, etc.
    html_content = html.unescape(html_content)
    
    # Check if content has HTML tags
    if '<' not in html_content or '>' not in html_content:
        return html_content, []
    
    # Try parsing with HTMLParser
    parser = HTMLContentExtractor()
    try:
        parser.feed(html_content)
        text, images = parser.get_content()
        # If we got text, make sure no img tags remain
        if text:
            # Extra safety: remove any remaining img tags from text
            text = re.sub(r'<img[^>]*>', '', text, flags=re.IGNORECASE)
            return text, images
    except Exception as e:
        # Log error and continue to fallback
        print(f"HTML parsing error: {e}")
    
    # Fallback: strip tags with regex
    try:
        # Remove script and style elements completely
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Extract ALL images before removing tags (with all variations)
        images = []
        # Pattern 1: Standard img tags
        images.extend(re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE))
        # Pattern 2: img tags with src as first attribute (no quotes sometimes)
        images.extend(re.findall(r'<img[^>]+src=([^\s>]+)', html_content, re.IGNORECASE))
        
        # Remove duplicate images
        images = list(dict.fromkeys(images))  # Preserve order while removing duplicates
        
        # Remove ALL img tags from text (with all variations)
        text = re.sub(r'<img[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<img[^>]*', '', text, flags=re.IGNORECASE)  # Even incomplete tags
        
        # Remove all other HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Decode HTML entities (again, in case some remain)
        text = html.unescape(text)
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text, images
    except Exception as e:
        print(f"Regex fallback error: {e}")
        # Last resort: return text without tags
        text = re.sub(r'<[^>]+>', '', html_content)
        return text, []


def clean_text(text):
    """Clean text by removing CDATA, HTML tags, and decoding entities"""
    if not text:
        return text
    
    # Remove CDATA wrappers
    text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', text, flags=re.DOTALL)
    
    # Unescape HTML entities first
    text = html.unescape(text)
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


class HTMLContentSanitizer(HTMLParser):
    """Parse HTML and extract only body content, removing unwanted tags and attributes"""
    
    # Tags to completely skip (including their content)
    SKIP_TAGS = {'script', 'style', 'head', 'meta', 'link', 'noscript'}
    
    # Tags to ignore but keep their content
    WRAPPER_TAGS = {'html', 'body'}
    
    # Attributes to remove from all tags
    REMOVE_ATTRS = {'class', 'id', 'style', 'onclick', 'onload', 'onerror'}
    
    # Attributes to keep only for specific tags
    KEEP_ATTRS = {
        'img': {'src', 'alt', 'title'},
        'a': {'href', 'title'},
        'iframe': {'src', 'width', 'height'},
    }
    
    def __init__(self):
        super().__init__()
        self.output = []
        self.skip_depth = 0  # Track depth of skipped tags
        
    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        
        # Skip unwanted tags
        if tag_lower in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        
        # If we're inside a skipped tag, don't output anything
        if self.skip_depth > 0:
            return
        
        # Wrapper tags - don't output the tag itself
        if tag_lower in self.WRAPPER_TAGS:
            return
        
        # Filter attributes
        filtered_attrs = []
        keep_attrs = self.KEEP_ATTRS.get(tag_lower, set())
        
        for attr_name, attr_value in attrs:
            attr_lower = attr_name.lower()
            # Keep specific attributes for specific tags
            if attr_lower in keep_attrs:
                # For images: truncate overly long alt/title text (usually photo credits)
                if tag_lower == 'img' and attr_lower in ('alt', 'title') and attr_value:
                    # Remove alt/title if longer than 100 chars (likely a caption/credit)
                    if len(attr_value) > 100:
                        continue  # Skip this attribute
                    # Otherwise truncate to 80 chars if needed
                    if len(attr_value) > 80:
                        attr_value = attr_value[:77] + '...'
                filtered_attrs.append((attr_name, attr_value))
            # Keep all attributes not in the remove list if no specific rules
            elif not keep_attrs and attr_lower not in self.REMOVE_ATTRS:
                filtered_attrs.append((attr_name, attr_value))
        
        # Add responsive style to images
        if tag_lower == 'img':
            filtered_attrs.append(('style', 'max-width: 100%; height: auto; display: block; margin: 10px 0;'))
        
        # Build tag with filtered attributes
        if filtered_attrs:
            attrs_str = ' '.join(f'{name}="{value}"' for name, value in filtered_attrs)
            self.output.append(f'<{tag} {attrs_str}>')
        else:
            self.output.append(f'<{tag}>')
    
    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        
        # Handle skipped tags
        if tag_lower in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        
        # If we're inside a skipped tag, don't output anything
        if self.skip_depth > 0:
            return
        
        # Wrapper tags - don't output the tag itself
        if tag_lower in self.WRAPPER_TAGS:
            return
        
        self.output.append(f'</{tag}>')
    
    def handle_data(self, data):
        # If we're inside a skipped tag, don't output the data
        if self.skip_depth > 0:
            return
        
        # Add text data
        if data.strip():
            self.output.append(data)
    
    def handle_startendtag(self, tag, attrs):
        """Handle self-closing tags like <img /> or <br />"""
        tag_lower = tag.lower()
        
        # Skip unwanted tags
        if tag_lower in self.SKIP_TAGS or self.skip_depth > 0:
            return
        
        # Wrapper tags - don't output
        if tag_lower in self.WRAPPER_TAGS:
            return
        
        # Filter attributes
        filtered_attrs = []
        keep_attrs = self.KEEP_ATTRS.get(tag_lower, set())
        
        for attr_name, attr_value in attrs:
            attr_lower = attr_name.lower()
            if attr_lower in keep_attrs:
                # For images: truncate overly long alt/title text (usually photo credits)
                if tag_lower == 'img' and attr_lower in ('alt', 'title') and attr_value:
                    # Remove alt/title if longer than 100 chars (likely a caption/credit)
                    if len(attr_value) > 100:
                        continue  # Skip this attribute
                    # Otherwise truncate to 80 chars if needed
                    if len(attr_value) > 80:
                        attr_value = attr_value[:77] + '...'
                filtered_attrs.append((attr_name, attr_value))
            elif not keep_attrs and attr_lower not in self.REMOVE_ATTRS:
                filtered_attrs.append((attr_name, attr_value))
        
        # Add responsive style to images
        if tag_lower == 'img':
            filtered_attrs.append(('style', 'max-width: 100%; height: auto; display: block; margin: 10px 0;'))
        
        # Build self-closing tag
        if filtered_attrs:
            attrs_str = ' '.join(f'{name}="{value}"' for name, value in filtered_attrs)
            self.output.append(f'<{tag} {attrs_str}>')
        else:
            self.output.append(f'<{tag}>')
    
    def get_content(self):
        """Return the sanitized HTML content"""
        result = ''.join(self.output)
        # Clean up extra whitespace
        result = re.sub(r'\s+', ' ', result)
        result = re.sub(r'>\s+<', '><', result)
        return result.strip()


def sanitize_html_content(html_content):
    """Sanitize HTML content using proper HTML parsing
    
    This function:
    - Parses HTML as a tree structure
    - Removes <html>, <head>, <body> wrapper tags
    - Removes <script>, <style> tags completely
    - Removes class, id, style attributes
    - Keeps content tags like <p>, <h1>, <img>, <a>
    - Preserves src/href/alt/title attributes where appropriate
    
    Returns clean HTML ready to be inserted into a <div>
    """
    if not html_content:
        return ""
    
    # Unescape HTML entities (in case content is stored escaped in DB)
    html_content = html.unescape(html_content)
    
    # Check if content has HTML tags
    if '<' not in html_content or '>' not in html_content:
        # Plain text - wrap in paragraph
        return f"<p>{html_content}</p>"
    
    # Parse HTML with custom parser
    parser = HTMLContentSanitizer()
    try:
        parser.feed(html_content)
        parser.close()  # Force parser to finish, handles incomplete HTML
        result = parser.get_content()
        
        # If result is empty or too short, fallback to plain text
        if not result or len(result.strip()) < 3:
            # Strip all HTML tags and return as plain text
            plain = re.sub(r'<[^>]*>', '', html_content)
            plain = re.sub(r'\s+', ' ', plain).strip()
            return f"<p>{plain}</p>" if plain else ""
        
        return result
    except Exception as e:
        # If parsing fails, return plain text
        print(f"HTML parsing error: {e}")
        # Strip all tags and return as paragraph
        text = re.sub(r'<[^>]+>', '', html_content)
        text = html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return f"<p>{text}</p>" if text else ""


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
        # Use AuiNotebook to allow closing tabs
        self.notebook = aui.AuiNotebook(self, 
            style=aui.AUI_NB_TOP | 
                  aui.AUI_NB_TAB_SPLIT | 
                  aui.AUI_NB_TAB_MOVE | 
                  aui.AUI_NB_CLOSE_ON_ACTIVE_TAB |
                  aui.AUI_NB_WINDOWLIST_BUTTON)
        
        # Tab 1: News List (cannot be closed)
        html_panel = wx.Panel(self.notebook)
        html_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # HTML Viewer for news list
        self.html_viewer = wx.html2.WebView.New(html_panel)
        html_sizer.Add(self.html_viewer, 1, wx.EXPAND | wx.ALL, 5)
        
        html_panel.SetSizer(html_sizer)
        self.notebook.AddPage(html_panel, "📰 News Feed", select=True)
        
        main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 0)
        
        self.SetSizer(main_sizer)
        
        # Bind events
        self.select_all_btn.Bind(wx.EVT_BUTTON, self.OnSelectAll)
        self.deselect_all_btn.Bind(wx.EVT_BUTTON, self.OnDeselectAll)
        self.load_checked_btn.Bind(wx.EVT_BUTTON, self.OnLoadChecked)
        self.sources_checklist.Bind(wx.EVT_CHECKLISTBOX, self.OnSourceChecked)
        self.sources_checklist.Bind(wx.EVT_LISTBOX, self.OnSourceSelected)
        
        # Bind navigation event to intercept link clicks
        self.html_viewer.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self.OnNavigating)
        
        # Bind notebook events
        self.notebook.Bind(aui.EVT_AUINOTEBOOK_PAGE_CLOSE, self.OnPageClose)
        
        # Initialize API client for real-time updates
        self.api_client = NewsAPIClient()
        self.polling_enabled = False
        self.current_source_ids = []  # Track currently displayed sources
        
        # Load data
        wx.CallAfter(self.LoadSources)
        wx.CallAfter(self.InitializeAPIPolling)
        
        # Setup polling timer (will start after API initialization)
        self.poll_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnPollTimer, self.poll_timer)
    
    def InitializeAPIPolling(self):
        """Initialize API client and get initial timestamp"""
        def init_in_thread():
            try:
                timestamp = self.api_client.get_initial_timestamp()
                if timestamp > 0:
                    wx.CallAfter(self.OnAPIInitialized, timestamp)
                else:
                    wx.CallAfter(self.OnAPIInitFailed)
            except Exception as e:
                logging.error(f"API initialization error: {e}")
                wx.CallAfter(self.OnAPIInitFailed)
        
        Thread(target=init_in_thread, daemon=True).start()
    
    def OnAPIInitialized(self, timestamp):
        """Called when API is successfully initialized"""
        logging.info(f"✅ API initialized with timestamp: {timestamp}")
        self.polling_enabled = True
        # Start polling timer
        self.poll_timer.Start(POLL_INTERVAL_MS)
        logging.info(f"🔄 Polling enabled (every {POLL_INTERVAL_MS/1000}s)")
    
    def OnAPIInitFailed(self):
        """Called when API initialization fails"""
        logging.warning("⚠️  API not available - polling disabled")
        self.polling_enabled = False
    
    def OnPollTimer(self, event):
        """Timer event handler for polling new articles"""
        if not self.polling_enabled or not self.current_source_ids:
            return
        
        def poll_in_thread():
            try:
                new_articles = self.api_client.poll_new_articles(
                    source_ids=self.current_source_ids,
                    limit=50
                )
                if new_articles:
                    wx.CallAfter(self.InsertNewArticles, new_articles)
            except Exception as e:
                logging.error(f"Polling error: {e}")
        
        Thread(target=poll_in_thread, daemon=True).start()
    
    def InsertNewArticles(self, articles):
        """Insert new articles at the top of the feed using JavaScript"""
        if not articles:
            return
        
        logging.info(f"📥 Inserting {len(articles)} new articles")
        
        # Generate HTML for new articles
        articles_html = ""
        for article in articles:
            article_html = self.GenerateArticleCardHTML(article)
            articles_html += article_html
        
        # Escape for JavaScript
        articles_html = articles_html.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
        
        # Execute JavaScript to insert new articles
        js_code = f"""
        (function() {{
            var articlesContainer = document.querySelector('.articles-container');
            if (articlesContainer) {{
                var tempDiv = document.createElement('div');
                tempDiv.innerHTML = '{articles_html}';
                
                // Insert each article at the beginning with animation
                var articles = tempDiv.querySelectorAll('.article');
                for (var i = articles.length - 1; i >= 0; i--) {{
                    var article = articles[i];
                    article.style.opacity = '0';
                    article.style.transform = 'translateY(-20px)';
                    article.style.transition = 'opacity 0.5s, transform 0.5s';
                    articlesContainer.insertBefore(article, articlesContainer.firstChild);
                    
                    // Trigger animation
                    setTimeout((function(el) {{
                        return function() {{
                            el.style.opacity = '1';
                            el.style.transform = 'translateY(0)';
                        }};
                    }})(article), 50 * (articles.length - i));
                }}
                
                // Show notification
                var notification = document.createElement('div');
                notification.className = 'new-articles-notification';
                notification.textContent = '{len(articles)} new article' + ({len(articles)} > 1 ? 's' : '') + ' loaded';
                notification.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #667eea; color: white; padding: 15px 25px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 1000; animation: slideIn 0.3s ease-out;';
                document.body.appendChild(notification);
                
                setTimeout(function() {{
                    notification.style.animation = 'slideOut 0.3s ease-out';
                    setTimeout(function() {{
                        notification.remove();
                    }}, 300);
                }}, 3000);
            }}
        }})();
        """
        
        self.html_viewer.RunScript(js_code)
    
    def GenerateArticleCardHTML(self, article):
        """Generate HTML for a single article card (for dynamic insertion)"""
        # Extract article data
        article_id = article.get('id_article', '')
        source_id = article.get('id_source', 'unknown')
        author = article.get('author', None)
        title = article.get('title', 'Untitled Article')
        description = article.get('description', None)
        url = article.get('url', '#')
        url_to_image = article.get('urlToImage', None)
        published_at_gmt = article.get('published_at_gmt', None)
        
        # Get source name
        source_name = self.sources.get(source_id, {}).get('name', source_id)
        
        # Format date
        date_str = "Just now"
        if published_at_gmt:
            try:
                dt = datetime.fromisoformat(published_at_gmt.replace('Z', '+00:00'))
                date_str = dt.strftime('%Y-%m-%d %H:%M GMT')
            except:
                pass
        
        # Clean and escape text
        title = clean_text(title).replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
        if author:
            author = clean_text(author).replace('<', '&lt;').replace('>', '&gt;')
        source_name = clean_text(source_name).replace('<', '&lt;').replace('>', '&gt;')
        
        # Sanitize description HTML
        description_html = ""
        if description:
            description_html = sanitize_html_content(description)
        
        # Build article card
        html = '<div class="article" style="animation: fadeIn 0.5s;">'
        html += f'<div class="article-title"><a href="{url}">{title}</a></div>'
        html += f'<div class="article-meta">'
        html += f'<span class="article-source">🔖 {source_name}</span>'
        if author:
            html += f'<span class="article-author">✍️ {author}</span>'
        html += f'<span class="article-date">📅 {date_str}</span>'
        html += '</div>'
        
        # Show main article image
        if url_to_image and url_to_image.startswith(('http://', 'https://')):
            html += f'<img src="{url_to_image}" alt="Article image" onerror="this.style.display=\'none\'" style="max-width: 100%; width: 100%; height: auto; display: block; margin: 10px 0; border-radius: 4px;">'
        
        # Show description
        if description_html:
            html += f'<div class="article-content">{description_html}</div>'
        
        html += '</div>'
        
        return html
    
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
    
    def OnNavigating(self, event):
        """Handle navigation event - intercept article link clicks"""
        url = event.GetURL()
        
        # Allow about:blank and file:// (local HTML)
        if url.startswith('about:') or url.startswith('file://'):
            return
        
        # If it's an external URL (http/https), open in new tab
        if url.startswith('http://') or url.startswith('https://'):
            # Prevent default navigation in news list viewer
            event.Veto()
            # Open in new tab
            self.OpenArticleTab(url)
            print(f"Opening article in new tab: {url}")
    
    def OnPageClose(self, event):
        """Handle tab close event - prevent closing the main tab"""
        # Get the page being closed
        page_idx = event.GetSelection()
        
        # Prevent closing the first tab (News Feed)
        if page_idx == 0:
            event.Veto()
            wx.MessageBox("Cannot close the main News Feed tab", 
                         "Info", wx.OK | wx.ICON_INFORMATION)
            print("Prevented closing main tab")
        else:
            print(f"Closing tab at index {page_idx}")
    
    def OpenArticleTab(self, url):
        """Open a news article in a new tab"""
        # Create new panel for the article
        article_panel = wx.Panel(self.notebook)
        article_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Add close button bar
        button_bar = wx.Panel(article_panel)
        button_bar.SetBackgroundColour(wx.Colour(240, 240, 240))
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        back_btn = wx.Button(button_bar, label="← Back to Feed", size=(120, 28))
        back_btn.Bind(wx.EVT_BUTTON, lambda evt: self.CloseArticleTab(article_panel))
        button_sizer.Add(back_btn, 0, wx.ALL, 5)
        
        url_text = wx.StaticText(button_bar, label=url)
        url_text.SetForegroundColour(wx.Colour(100, 100, 100))
        button_sizer.Add(url_text, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        button_bar.SetSizer(button_sizer)
        article_sizer.Add(button_bar, 0, wx.EXPAND)
        
        # Create WebView for the article
        article_viewer = wx.html2.WebView.New(article_panel)
        article_viewer.LoadURL(url)
        article_sizer.Add(article_viewer, 1, wx.EXPAND)
        
        article_panel.SetSizer(article_sizer)
        
        # Extract title from URL for tab label
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            tab_title = parsed.netloc.replace('www.', '')[:20]
        except:
            tab_title = "Article"
        
        # Add the new tab
        self.notebook.AddPage(article_panel, f"📄 {tab_title}", select=True)
        print(f"Opened new tab: {tab_title}")
    
    def CloseArticleTab(self, panel):
        """Close an article tab"""
        # Find the page index
        for i in range(self.notebook.GetPageCount()):
            if self.notebook.GetPage(i) == panel:
                if i > 0:  # Don't close main tab
                    self.notebook.DeletePage(i)
                    # Return to main tab
                    self.notebook.SetSelection(0)
                    print(f"Closed article tab at index {i}")
                break
    
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
            self.current_source_ids = []
            return
        
        print(f"\n=== Loading articles from {len(checked_source_ids)} checked sources ===")
        
        # Update current source IDs for polling
        self.current_source_ids = checked_source_ids
        
        try:
            eng = dbOpen()
            meta = MetaData()
            gm_articles = Table('gm_articles', meta, autoload_with=eng)
            
            con = eng.connect()
            
            # Load articles from all checked sources
            # Filter out articles scheduled more than 24 hours in the future (keep NULL dates)
            stm = select(gm_articles).where(
                gm_articles.c.id_source.in_(checked_source_ids),
                (gm_articles.c.published_at_gmt.is_(None)) | (gm_articles.c.published_at_gmt <= func.datetime('now', '+1 day'))
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
            
            # Update current source IDs for polling
            self.current_source_ids = [source_id]
            
            eng = dbOpen()
            meta = MetaData()
            gm_articles = Table('gm_articles', meta, autoload_with=eng)
            
            con = eng.connect()
            
            # Load articles for this source, prefer published_at_gmt
            # Filter out articles scheduled more than 24 hours in the future (keep NULL dates)
            stm = select(gm_articles).where(
                gm_articles.c.id_source == source_id,
                (gm_articles.c.published_at_gmt.is_(None)) | (gm_articles.c.published_at_gmt <= func.datetime('now', '+1 day'))
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
                .articles-container {{
                    /* Container for dynamic article insertion */
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
                @keyframes fadeIn {{
                    from {{ opacity: 0; transform: translateY(-10px); }}
                    to {{ opacity: 1; transform: translateY(0); }}
                }}
                @keyframes slideIn {{
                    from {{ transform: translateX(100%); opacity: 0; }}
                    to {{ transform: translateX(0); opacity: 1; }}
                }}
                @keyframes slideOut {{
                    from {{ transform: translateX(0); opacity: 1; }}
                    to {{ transform: translateX(100%); opacity: 0; }}
                }}
                .new-articles-notification {{
                    animation: slideIn 0.3s ease-out;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📰 Combined News Feed</h1>
                <div class="subtitle">{article_count} articles from {source_count} sources</div>
                <div class="subtitle" style="margin-top: 5px; font-size: 14px;">{subtitle}</div>
            </div>
            <div class="articles-container">
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
            
            # Clean title, author, and source name (remove CDATA, HTML tags)
            title = clean_text(title)
            if author:
                author = clean_text(author)
            source_name = clean_text(source_name)
            
            # Escape title, author, and source for safe HTML display
            title = title.replace('<', '&lt;').replace('>', '&gt;').replace('\"', '&quot;')
            if author:
                author = author.replace('<', '&lt;').replace('>', '&gt;')
            source_name = source_name.replace('<', '&lt;').replace('>', '&gt;')
            
            # Sanitize HTML description (keep images and structure, remove classes/styles)
            description_html = ""
            if description:
                description_html = sanitize_html_content(description)
            
            # Build article card
            html += '<div class="article">'
            html += f'<div class="article-title"><a href="{url}">{title}</a></div>'
            html += f'<div class="article-meta">'
            html += f'<span class="article-source">🔖 {source_name}</span>'
            if author:
                html += f'<span class="article-author">✍️ {author}</span>'
            html += f'<span class="article-date">📅 {date_str}</span>'
            html += '</div>'
            
            # Show main article image if available (from urlToImage field)
            if url_to_image and url_to_image.startswith(('http://', 'https://')):
                html += f'<img src="{url_to_image}" alt="Article image" onerror="this.style.display=\'none\'" style="max-width: 100%; width: 100%; height: auto; display: block; margin: 10px 0; border-radius: 4px; clear: both;">'
            
            # Show sanitized description HTML (includes images and content structure)
            if description_html:
                html += f'<div class="article-content">{description_html}</div>'
            
            html += '</div>'  # Close article div
        
        html += """
            </div>  <!-- Close articles-container -->
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
                .articles-container {{
                    /* Container for dynamic article insertion */
                }}
                @keyframes fadeIn {{
                    from {{ opacity: 0; transform: translateY(-10px); }}
                    to {{ opacity: 1; transform: translateY(0); }}
                }}
                @keyframes slideIn {{
                    from {{ transform: translateX(100%); opacity: 0; }}
                    to {{ transform: translateX(0); opacity: 1; }}
                }}
                @keyframes slideOut {{
                    from {{ transform: translateX(0); opacity: 1; }}
                    to {{ transform: translateX(100%); opacity: 0; }}
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📰 {source_name}</h1>
                <div class="subtitle">{article_count} recent articles</div>
            </div>
            <div class="articles-container">
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
            
            # Clean title and author (remove CDATA, HTML tags)
            title = clean_text(title)
            if author:
                author = clean_text(author)
            
            # Escape title and author for safe HTML display
            title = title.replace('<', '&lt;').replace('>', '&gt;').replace('\"', '&quot;')
            if author:
                author = author.replace('<', '&lt;').replace('>', '&gt;')
            
            # Sanitize HTML description (keep images and structure, remove classes/styles)
            description_html = ""
            if description:
                description_html = sanitize_html_content(description)
            
            # Build article card
            html += '<div class="article">'
            html += f'<div class="article-title"><a href="{url}">{title}</a></div>'
            html += f'<div class="article-meta">'
            if author:
                html += f'<span class="article-author">✍️ {author}</span>'
            html += f'<span class="article-date">📅 {date_str}</span>'
            html += '</div>'
            
            # Show main article image if available (from urlToImage field)
            if url_to_image and url_to_image.startswith(('http://', 'https://')):
                html += f'<img src="{url_to_image}" alt="Article image" onerror="this.style.display=\'none\'" style="max-width: 100%; width: 100%; height: auto; display: block; margin: 10px 0; border-radius: 4px; clear: both;">'
            
            # Show sanitized description HTML (includes images and content structure)
            if description_html:
                html += f'<div class="article-content">{description_html}</div>'
            
            html += '</div>'  # Close article div
        
        html += """
            </div>  <!-- Close articles-container -->
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
