#!/usr/bin/env python3
"""Test improved sanitization"""

import re
import html as html_module

def sanitize_html_content(html_content):
    """Sanitize HTML content - IMPROVED VERSION"""
    if not html_content:
        return ""
    
    html_content = html_module.unescape(html_content)
    
    if '<' not in html_content or '>' not in html_content:
        return f"<p>{html_content}</p>"
    
    # Remove script and style tags completely (multiple passes)
    for _ in range(3):
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    
    # AGGRESSIVE removal of HTML document structure tags
    html_content = re.sub(r'<!DOCTYPE[^>]*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<html[^>]*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<html>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'</html\s*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'</html>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<head[^>]*>.*?</head>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<head>.*?</head>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<body[^>]*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<body>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'</body\s*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'</body>', '', html_content, flags=re.IGNORECASE)
    
    # Remove attributes
    html_content = re.sub(r'\sclass\s*=\s*["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sclass\s*=\s*[^\s>]+', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sstyle\s*=\s*["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sstyle\s*=\s*[^\s>]+', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sid\s*=\s*["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\sid\s*=\s*[^\s>]+', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\salign\s*=\s*["\']?[^"\'\s>]*["\']?', '', html_content, flags=re.IGNORECASE)
    
    # Fix img tags
    html_content = re.sub(
        r'<img\s+([^>]*)>',
        r'<img \1 style="max-width: 100%; height: auto; display: block; margin: 10px 0;">',
        html_content,
        flags=re.IGNORECASE
    )
    
    # Clean up whitespace
    html_content = re.sub(r'\s+', ' ', html_content)
    html_content = re.sub(r'>\s+<', '><', html_content)
    html_content = html_content.strip()
    
    return html_content


# Test cases
print("=" * 80)
print("TEST 1: Full HTML document with DOCTYPE")
print("=" * 80)

test1 = """<!DOCTYPE html>
<html lang="en">
<head>
    <title>Test</title>
    <style>.test { color: red; }</style>
</head>
<body class="main" id="content">
    <h1>Title</h1>
    <p class="para" style="color: blue;">Text content</p>
    <img src="test.jpg" alt="Test" width="500" height="300">
</body>
</html>"""

result1 = sanitize_html_content(test1)
print(f"Result:\n{result1}\n")

if '<html>' in result1.lower() or '</html>' in result1.lower():
    print("❌ FAIL: <html> tag still present!")
else:
    print("✅ PASS: No <html> tags")

if '<body>' in result1.lower() or '</body>' in result1.lower():
    print("❌ FAIL: <body> tag still present!")
else:
    print("✅ PASS: No <body> tags")

if '<head>' in result1.lower():
    print("❌ FAIL: <head> section still present!")
else:
    print("✅ PASS: No <head> section")

if 'class=' in result1.lower():
    print("❌ FAIL: class attributes still present!")
else:
    print("✅ PASS: No class attributes")

if '<h1>' in result1 and '<p>' in result1 and '<img' in result1:
    print("✅ PASS: Content tags preserved")
else:
    print("❌ FAIL: Content tags lost!")

print("\n" + "=" * 80)
print("TEST 2: Variations with spaces and case")
print("=" * 80)

test2 = """< HTML >
<BODY>
<P>Content</P>
< / body >
< / HTML >"""

result2 = sanitize_html_content(test2)
print(f"Result: {result2}")

if 'html' not in result2.lower() or result2.count('<') <= 2:
    print("✅ PASS: HTML tags removed (even with spaces)")
else:
    print(f"❌ FAIL: HTML tags still present")
