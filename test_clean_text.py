#!/usr/bin/env python3
"""Test clean_text function"""

import re
import html

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

# Test cases from screenshot
print("=" * 80)
print("TEST 1: CDATA wrapper")
print("=" * 80)
test1 = '<![CDATA[ Jéssica Athayde fala sobre aumentar a família com Diogo Amaral: "Se vier mais um..." ]]>'
result1 = clean_text(test1)
print(f"Input:  {test1}")
print(f"Output: {result1}")
print()

print("=" * 80)
print("TEST 2: HTML tag in title")
print("=" * 80)
test2 = '<p>IVECO CUS Torino batte Avezzano: vittoria pesante in chiave playoff</p>'
result2 = clean_text(test2)
print(f"Input:  {test2}")
print(f"Output: {result2}")
print()

print("=" * 80)
print("TEST 3: Mixed - CDATA + tags + entities")
print("=" * 80)
test3 = '<![CDATA[<div>Test &amp; example &lt;content&gt;</div>]]>'
result3 = clean_text(test3)
print(f"Input:  {test3}")
print(f"Output: {result3}")
print()

print("=" * 80)
print("TEST 4: Already clean text")
print("=" * 80)
test4 = 'Simple text without markup'
result4 = clean_text(test4)
print(f"Input:  {test4}")
print(f"Output: {result4}")
print()

print("✅ All tests completed!")
