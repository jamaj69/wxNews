#!/usr/bin/env python3
"""Test parse_html_description with actual problematic image tag"""

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
    """Parse HTML description - improved version"""
    if not html_content:
        return "", []
    
    html_content = html_module.unescape(html_content)
    
    if '<' not in html_content or '>' not in html_content:
        return html_content, []
    
    parser = HTMLContentExtractor()
    try:
        parser.feed(html_content)
        text, images = parser.get_content()
        if text:
            # Extra safety: remove any remaining img tags from text
            text = re.sub(r'<img[^>]*>', '', text, flags=re.IGNORECASE)
            return text, images
    except Exception as e:
        print(f"Parser error: {e}")
    
    # Fallback
    try:
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Extract ALL images (multiple patterns)
        images = []
        images.extend(re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE))
        images.extend(re.findall(r'<img[^>]+src=([^\s>]+)', html_content, re.IGNORECASE))
        images = list(dict.fromkeys(images))
        
        # Remove ALL img tags
        text = re.sub(r'<img[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<img[^>]*', '', text, flags=re.IGNORECASE)
        
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text, images
    except Exception as e:
        print(f"Fallback error: {e}")
        text = re.sub(r'<[^>]+>', '', html_content)
        return text, []


# Test with actual problematic image from screenshot
problematic_img = '''<img align="right" alt="Saudi Crown Prince Mohammed bin Salman makes his way to greet US President Donald Trump upon his arrival in Riyadh, Saudi Arabia, May 13, 2025 (photo credit: BRENDAN SMIALOWSKI/AFP via Getty Images)" src="https://images.jpost.com/image/upload/f_auto,fl_lossy/q_auto/c_fill,g_faces:center,h_537,w_822/710007" title="Saudi Crown Prince Mohammed bin Salman makes his way to greet US President Donald Trump upon his arrival in Riyadh, Saudi Arabia, May 13, 2025 (photo credit: BRE'''

print("=" * 80)
print("TEST: Problematic image tag from screenshot")
print("=" * 80)
print(f"Input (first 150 chars): {problematic_img[:150]}...")
print()

text, images = parse_html_description(problematic_img)

print(f"Extracted text: '{text}'")
print(f"Extracted {len(images)} image(s):")
for img in images:
    print(f"  - {img}")
print()

if '<img' in text.lower():
    print("❌ FAIL: <img> tag still in text!")
else:
    print("✅ SUCCESS: No <img> tags in text")

if len(images) > 0:
    print("✅ SUCCESS: Image extracted")
else:
    print("❌ FAIL: No images extracted")
