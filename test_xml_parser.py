#!/usr/bin/env python3
"""Test XML-based HTML sanitization"""

import re
import html as html_module
from html.parser import HTMLParser

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
        self.skip_depth = 0
        
    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        
        if tag_lower in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        
        if self.skip_depth > 0:
            return
        
        if tag_lower in self.WRAPPER_TAGS:
            return
        
        # Filter attributes
        filtered_attrs = []
        keep_attrs = self.KEEP_ATTRS.get(tag_lower, set())
        
        for attr_name, attr_value in attrs:
            attr_lower = attr_name.lower()
            if attr_lower in keep_attrs:
                filtered_attrs.append((attr_name, attr_value))
            elif not keep_attrs and attr_lower not in self.REMOVE_ATTRS:
                filtered_attrs.append((attr_name, attr_value))
        
        if tag_lower == 'img':
            filtered_attrs.append(('style', 'max-width: 100%; height: auto; display: block; margin: 10px 0;'))
        
        if filtered_attrs:
            attrs_str = ' '.join(f'{name}="{value}"' for name, value in filtered_attrs)
            self.output.append(f'<{tag} {attrs_str}>')
        else:
            self.output.append(f'<{tag}>')
    
    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        
        if tag_lower in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        
        if self.skip_depth > 0:
            return
        
        if tag_lower in self.WRAPPER_TAGS:
            return
        
        self.output.append(f'</{tag}>')
    
    def handle_data(self, data):
        if self.skip_depth > 0:
            return
        
        if data.strip():
            self.output.append(data)
    
    def handle_startendtag(self, tag, attrs):
        tag_lower = tag.lower()
        
        if tag_lower in self.SKIP_TAGS or self.skip_depth > 0:
            return
        
        if tag_lower in self.WRAPPER_TAGS:
            return
        
        filtered_attrs = []
        keep_attrs = self.KEEP_ATTRS.get(tag_lower, set())
        
        for attr_name, attr_value in attrs:
            attr_lower = attr_name.lower()
            if attr_lower in keep_attrs:
                filtered_attrs.append((attr_name, attr_value))
            elif not keep_attrs and attr_lower not in self.REMOVE_ATTRS:
                filtered_attrs.append((attr_name, attr_value))
        
        if tag_lower == 'img':
            filtered_attrs.append(('style', 'max-width: 100%; height: auto; display: block; margin: 10px 0;'))
        
        if filtered_attrs:
            attrs_str = ' '.join(f'{name}="{value}"' for name, value in filtered_attrs)
            self.output.append(f'<{tag} {attrs_str}>')
        else:
            self.output.append(f'<{tag}>')
    
    def get_content(self):
        result = ''.join(self.output)
        result = re.sub(r'\s+', ' ', result)
        result = re.sub(r'>\s+<', '><', result)
        return result.strip()


def sanitize_html_content(html_content):
    if not html_content:
        return ""
    
    html_content = html_module.unescape(html_content)
    
    if '<' not in html_content or '>' not in html_content:
        return f"<p>{html_content}</p>"
    
    parser = HTMLContentSanitizer()
    try:
        parser.feed(html_content)
        result = parser.get_content()
        
        if not result or len(result) < 3:
            return f"<p>{html_content}</p>"
        
        return result
    except Exception as e:
        print(f"HTML parsing error: {e}")
        text = re.sub(r'<[^>]+>', '', html_content)
        text = html_module.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return f"<p>{text}</p>" if text else ""


# Test cases
print("=" * 80)
print("TEST 1: Full HTML document with all wrapper tags")
print("=" * 80)

test1 = """<!DOCTYPE html>
<html lang="en">
<head>
    <title>Test Page</title>
    <style>body { color: red; }</style>
    <script>alert('test');</script>
</head>
<body class="main-body" id="content" style="background: white;">
    <h1 class="title" id="main-title">Article Title</h1>
    <p class="paragraph" style="color: blue;">This is the content paragraph.</p>
    <img src="test.jpg" alt="Test Image" class="photo" style="width: 500px;" width="500" height="300">
    <a href="http://example.com" class="link">Click here</a>
</body>
</html>"""

result1 = sanitize_html_content(test1)
print(f"\nResult:\n{result1}\n")

# Checks
checks = {
    "No <html> tags": '<html>' not in result1.lower() and '</html>' not in result1.lower(),
    "No <body> tags": '<body>' not in result1.lower() and '</body>' not in result1.lower(),
    "No <head> section": '<head>' not in result1.lower() and 'Test Page' not in result1,
    "No <style> content": '<style>' not in result1.lower() and 'color: red' not in result1,
    "No <script> content": '<script>' not in result1.lower() and "alert" not in result1,
    "No class attributes": 'class=' not in result1.lower(),
    "No id attributes": 'id=' not in result1.lower(),
    "<h1> preserved": '<h1>' in result1,
    "<p> preserved": '<p>' in result1,
    "<img> preserved with src": '<img' in result1 and 'src="test.jpg"' in result1,
    "<a> preserved with href": '<a' in result1 and 'href="http://example.com"' in result1,
    "Content text present": 'Article Title' in result1 and 'content paragraph' in result1,
}

for check, passed in checks.items():
    status = "✅" if passed else "❌"
    print(f"{status} {check}")

print("\n" + "=" * 80)
print("TEST 2: Simple HTML with img tag")
print("=" * 80)

test2 = '<h1>Title</h1><p><img src="image.jpg" /><hr /></p>'
result2 = sanitize_html_content(test2)
print(f"Input: {test2}")
print(f"Result: {result2}")
print()

if '<h1>' in result2 and '<img' in result2:
    print("✅ Tags preserved")
else:
    print("❌ Tags lost")

print("\n" + "=" * 80)
print("TEST 3: Plain text (no HTML)")
print("=" * 80)

test3 = "Just plain text"
result3 = sanitize_html_content(test3)
print(f"Input: {test3}")
print(f"Result: {result3}")

if '<p>' in result3 and 'Just plain text' in result3:
    print("✅ Plain text wrapped in <p>")
else:
    print("❌ Plain text not handled correctly")
