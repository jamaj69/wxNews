#!/usr/bin/env python3
"""Test with actual HTML from database"""

import re
import html as html_module

def sanitize_html_content(html_content):
    """Sanitize HTML content"""
    if not html_content:
        return ""
    
    print("=" * 80)
    print(f"STEP 1: Original (first 300 chars)")
    print("=" * 80)
    print(html_content[:300])
    
    # Unescape HTML entities (in case content is stored escaped in DB)
    html_content = html_module.unescape(html_content)
    
    print("\n" + "=" * 80)
    print(f"STEP 2: After unescape (first 300 chars)")
    print("=" * 80)
    print(html_content[:300])
    
    # Check if content has HTML tags
    if '<' not in html_content or '>' not in html_content:
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
    
    print("\n" + "=" * 80)
    print(f"STEP 3: After removing html/body tags (first 300 chars)")
    print("=" * 80)
    print(html_content[:300])
    
    # Remove class attributes
    html_content = re.sub(r'\sclass=["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sclass=[^\s>]+', '', html_content, flags=re.IGNORECASE)
    
    # Remove style attributes
    html_content = re.sub(r'\sstyle=["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sstyle=[^\s>]+', '', html_content, flags=re.IGNORECASE)
    
    # Remove align attributes
    html_content = re.sub(r'\salign=["\']?[^"\'\s>]*["\']?', '', html_content, flags=re.IGNORECASE)
    
    # Fix img tags
    html_content = re.sub(
        r'<img\s+([^>]*)>',
        r'<img \1 style="max-width: 100%; height: auto; display: block; margin: 10px 0;">',
        html_content,
        flags=re.IGNORECASE
    )
    
    # Clean up whitespace
    html_content = re.sub(r'\s+', ' ', html_content).strip()
    
    print("\n" + "=" * 80)
    print(f"STEP 4: Final result (first 500 chars)")
    print("=" * 80)
    print(html_content[:500])
    
    return html_content


# Test with actual description from database
test_description = '''<h1>Kanamara Matsuri has been an annual tradition since 1969, and besides being known for its fun, it raises money for a good cause.</h1><p><img src="https://img.buzzfeed.com/buzzfeed-static/static/2023-04/7/14/asset/d00ee62a8b00/sub-buzz-711-1680877174-16.jpg?crop=1997:1331;0,0&amp;resize=1250:830" /></p><hr /><p><a href="https://www.buzzfeednews.com/article/kennethbachor/japans-annual-penis-festival-photos">View Entire Post &rsaquo;</a></p>'''

print("\n\n")
print("#" * 80)
print("TESTING WITH ACTUAL DATABASE HTML")
print("#" * 80)
print()

result = sanitize_html_content(test_description)

print("\n\n" + "=" * 80)
print("VERIFICATION")
print("=" * 80)

if '<h1>' in result:
    print("✅ <h1> tag preserved")
if '<img' in result:
    print("✅ <img> tag preserved")
if '<html>' in result.lower():
    print("❌ ERROR: <html> tag found!")
else:
    print("✅ No <html> tag")
if '<body>' in result.lower():
    print("❌ ERROR: <body> tag found!")
else:
    print("✅ No <body> tag")
if '&amp;' in result:
    print("⚠️ WARNING: &amp; entity not unescaped!")
else:
    print("✅ Entities unescaped")
