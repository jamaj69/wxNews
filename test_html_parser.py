#!/usr/bin/env python3
"""Test HTML parser functionality"""

import re
import html as html_module
from html.parser import HTMLParser

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
    """Parse HTML description - with unescape"""
    if not html_content:
        return "", []
    
    # IMPORTANT: Unescape HTML entities first
    html_content = html_module.unescape(html_content)
    
    if '<' not in html_content or '>' not in html_content:
        return html_content, []
    
    parser = HTMLContentExtractor()
    try:
        parser.feed(html_content)
        text, images = parser.get_content()
        if text:
            return text, images
    except Exception as e:
        print(f"Parser error: {e}")
    
    # Fallback
    text = re.sub(r'<[^>]+>', '', html_content)
    text = html_module.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    images = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    return text, images


# Test 1: Normal HTML
sample_html = '''<div class="editorial-container__name">Internacional</div> <div><h3>ESCRITO POR:</h3> <img src="https://example.com/image.png" /></div> <p>Nayib Bukele criticó un informe presentado ante la CIDH</p>'''

print("="* 80)
print("TEST 1: Normal HTML")
print("=" * 80)
print(f"Input: {sample_html[:100]}...")
text, images = parse_html_description(sample_html)
print(f"✅ Text: {text}")
print(f"✅ Images: {images}")

# Test 2: Escaped HTML (como vem do banco de dados)
escaped_html = html_module.escape(sample_html)
print("\n" + "=" * 80)
print("TEST 2: Escaped HTML (from database)")
print("=" * 80)
print(f"Input: {escaped_html[:100]}...")
text, images = parse_html_description(escaped_html)
print(f"✅ Text: {text}")
print(f"✅ Images: {images}")

# Test 3: Partial escaping (mixed)
partial = '&lt;div&gt;Test &lt;img src="https://example.com/test.jpg" /&gt; content&lt;/div&gt;'
print("\n" + "=" * 80)
print("TEST 3: Partially escaped")
print("=" * 80)
print(f"Input: {partial}")
text, images = parse_html_description(partial)
print(f"✅ Text: {text}")
print(f"✅ Images: {images}")
