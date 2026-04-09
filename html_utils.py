"""
html_utils.py — shared HTML sanitization and image-extraction helpers.

Moved out of wxAsyncNewsGather.py so that enrichment_worker.py can import
them without creating a circular dependency.
"""

import re
from html.parser import HTMLParser
import html


# ---------------------------------------------------------------------------
# Encoding fix
# ---------------------------------------------------------------------------

def fix_encoding_if_needed(text):
    """
    Detect and fix encoding issues where UTF-8 was misinterpreted as Latin-1.

    Common signs: 'Ã£' should be 'ã', 'Ã©' should be 'é', 'Ã§Ã£' should be
    'ção', etc.  Multiple passes may be needed for double-encoding issues.
    """
    if not text:
        return text

    max_iterations = 3  # Prevent infinite loops

    for _ in range(max_iterations):
        if 'Ã' not in text:
            break
        try:
            fixed = text.encode('latin-1').decode('utf-8')
            if fixed == text:
                break
            if fixed.count('Ã') < text.count('Ã'):
                text = fixed
            else:
                break
        except (UnicodeDecodeError, UnicodeEncodeError):
            break

    return text


# ---------------------------------------------------------------------------
# HTML sanitizer
# ---------------------------------------------------------------------------

class HTMLContentSanitizer(HTMLParser):
    """Parse HTML and extract only body content, removing unwanted tags/attrs."""

    # Tags to completely skip (including their content)
    SKIP_TAGS = {'script', 'style', 'head', 'meta', 'link', 'noscript'}

    # Tags to ignore but keep their content
    WRAPPER_TAGS = {'html', 'body', 'div', 'span', 'section', 'article'}

    # Attributes to remove from all tags
    REMOVE_ATTRS = {'class', 'id', 'style', 'onclick', 'onload', 'onerror',
                    'align', 'width', 'height'}

    # Tags we want to keep in output
    KEEP_TAGS = {'p', 'br', 'img', 'a', 'b', 'i', 'strong', 'em', 'u'}

    # Attributes to keep for specific tags
    KEEP_ATTRS = {
        'img': {'src', 'alt'},
        'a': {'href'},
    }

    def __init__(self):
        super().__init__()
        self.content = []
        self.skip_level = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_level += 1
            return
        if self.skip_level > 0:
            return
        if tag in self.WRAPPER_TAGS:
            return
        if tag not in self.KEEP_TAGS:
            return

        allowed_attrs = self.KEEP_ATTRS.get(tag, set())
        filtered_attrs = []
        for attr, value in attrs:
            if attr not in self.REMOVE_ATTRS and (not allowed_attrs or attr in allowed_attrs):
                if attr == 'alt' and value and len(value) > 100:
                    continue
                filtered_attrs.append((attr, value))

        if filtered_attrs:
            attrs_str = ' '.join(f'{a}="{v}"' for a, v in filtered_attrs)
            self.content.append(f'<{tag} {attrs_str}>')
        else:
            self.content.append(f'<{tag}>')

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self.skip_level = max(0, self.skip_level - 1)
            return
        if self.skip_level > 0:
            return
        if tag in self.WRAPPER_TAGS:
            return
        if tag not in self.KEEP_TAGS:
            return
        self.content.append(f'</{tag}>')

    def handle_data(self, data):
        if self.skip_level == 0:
            self.content.append(data)

    def handle_startendtag(self, tag, attrs):
        if tag in self.SKIP_TAGS or self.skip_level > 0:
            return
        if tag in self.WRAPPER_TAGS:
            return
        if tag not in self.KEEP_TAGS:
            return

        allowed_attrs = self.KEEP_ATTRS.get(tag, set())
        filtered_attrs = []
        for attr, value in attrs:
            if attr not in self.REMOVE_ATTRS and (not allowed_attrs or attr in allowed_attrs):
                if attr == 'alt' and value and len(value) > 100:
                    continue
                filtered_attrs.append((attr, value))

        if filtered_attrs:
            attrs_str = ' '.join(f'{a}="{v}"' for a, v in filtered_attrs)
            self.content.append(f'<{tag} {attrs_str} />')
        else:
            self.content.append(f'<{tag} />')

    def get_content(self):
        return ''.join(self.content)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def sanitize_html_content(html_content):
    """
    Sanitize HTML content.

    Removes: <script>, <style>, class/id/style attributes, wrapper tags.
    Keeps: <p>, <img>, <a>, <b>, <i>, <strong>, <em>, <u>, src/href/alt.
    """
    if not html_content:
        return ""

    html_content = fix_encoding_if_needed(html_content)
    html_content = html.unescape(html_content)

    if '<' not in html_content or '>' not in html_content:
        return f"<p>{html_content}</p>"

    parser = HTMLContentSanitizer()
    try:
        parser.feed(html_content)
        parser.close()
        result = parser.get_content()

        if not result or len(result.strip()) < 3:
            plain = re.sub(r'<[^>]*>', '', html_content)
            plain = re.sub(r'\s+', ' ', plain).strip()
            return f"<p>{plain}</p>" if plain else ""

        return result.strip()
    except Exception:
        plain = re.sub(r'<[^>]*>', '', html_content)
        plain = re.sub(r'\s+', ' ', plain).strip()
        return f"<p>{plain}</p>" if plain else ""


def extract_first_image_url(html_content):
    """Extract the first image URL from HTML content (HTTP/HTTPS only)."""
    if not html_content:
        return None
    try:
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        if img_match:
            url = img_match.group(1)
            if url.startswith(('http://', 'https://')):
                return url
    except Exception:
        pass
    return None


def extract_and_remove_first_image(html_content):
    """
    Extract the first image URL from HTML and remove that img tag.

    Returns:
        tuple: (image_url | None, cleaned_html)
    """
    if not html_content:
        return None, html_content
    try:
        img_match = re.search(
            r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', html_content, re.IGNORECASE
        )
        if img_match:
            url = img_match.group(1)
            if url.startswith(('http://', 'https://')):
                cleaned = html_content[:img_match.start()] + html_content[img_match.end():]
                return url, cleaned
    except Exception:
        pass
    return None, html_content
