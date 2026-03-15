#!/usr/bin/env python3
"""Test sanitize_html_content function"""

import re
import html as html_module

def sanitize_html_content(html_content):
    """Sanitize HTML content: keep structure and images, but remove classes, styles, and unwanted tags"""
    if not html_content:
        return ""
    
    # Unescape HTML entities (in case content is stored escaped in DB)
    html_content = html_module.unescape(html_content)
    
    # Check if content has HTML tags
    if '<' not in html_content or '>' not in html_content:
        # Plain text - wrap in paragraph
        return f"<p>{html_content}</p>"
    
    # Remove script and style tags completely
    html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove <html>, <head>, <body> wrapper tags (but keep their content)
    html_content = re.sub(r'<html[^>]*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'</html>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<head[^>]*>.*?</head>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<body[^>]*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'</body>', '', html_content, flags=re.IGNORECASE)
    
    # Remove class attributes from all tags
    html_content = re.sub(r'\sclass=["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sclass=[^\s>]+', '', html_content, flags=re.IGNORECASE)
    
    # Remove style attributes from all tags
    html_content = re.sub(r'\sstyle=["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sstyle=[^\s>]+', '', html_content, flags=re.IGNORECASE)
    
    # Remove align attributes (deprecated HTML)
    html_content = re.sub(r'\salign=["\']?[^"\'\s>]*["\']?', '', html_content, flags=re.IGNORECASE)
    
    # Fix img tags: ensure they have basic styling for responsive display
    html_content = re.sub(
        r'<img\s+([^>]*)>',
        r'<img \1 style="max-width: 100%; height: auto; display: block; margin: 10px 0;">',
        html_content,
        flags=re.IGNORECASE
    )
    
    # Clean up whitespace
    html_content = re.sub(r'\s+', ' ', html_content).strip()
    
    return html_content


# Test cases
print("=" * 80)
print("TEST 1: Problematic image tag from screenshot")
print("=" * 80)

test1 = '''<img align="right" alt="Saudi Crown Prince Mohammed bin Salman" src="https://images.jpost.com/image/upload/f_auto,fl_lossy/q_auto/c_fill,g_faces:center,h_537,w_822/710007" title="Saudi Crown Prince">'''

result1 = sanitize_html_content(test1)
print(f"Input: {test1[:100]}...")
print(f"Output: {result1[:150]}...")
print()

if '<img' in result1.lower() and 'src=' in result1.lower():
    print("✅ Image tag preserved")
else:
    print("❌ Image tag lost")

if 'align=' not in result1.lower():
    print("✅ align attribute removed")
else:
    print("❌ align attribute still present")

print()
print("=" * 80)
print("TEST 2: HTML with paragraphs and classes")
print("=" * 80)

test2 = '''<html><body><p class="main-text" style="color: red;">This is a paragraph with a class.</p><img src="test.jpg" class="photo"><p>Another paragraph.</p></body></html>'''

result2 = sanitize_html_content(test2)
print(f"Input: {test2}")
print(f"Output: {result2}")
print()

if '<html>' not in result2 and '<body>' not in result2:
    print("✅ HTML/body tags removed")
else:
    print("❌ HTML/body tags still present")

if 'class=' not in result2:
    print("✅ class attributes removed")
else:
    print("❌ class attributes still present")

if '<p>' in result2 and '<img' in result2:
    print("✅ Content tags preserved")
else:
    print("❌ Content tags lost")

print()
print("=" * 80)
print("TEST 3: Plain text (no HTML)")
print("=" * 80)

test3 = "Just plain text without any HTML tags"
result3 = sanitize_html_content(test3)
print(f"Input: {test3}")
print(f"Output: {result3}")
print()

if '<p>' in result3:
    print("✅ Plain text wrapped in <p>")
else:
    print("❌ Plain text not wrapped")
