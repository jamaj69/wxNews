#!/usr/bin/env python3
"""Test with the actual problematic image"""

import re
import html as html_module
from html.parser import HTMLParser

# Load the sanitizer
exec(open('wxAsyncNewsReaderv6.py').read().split('class NewsPanel')[0])

# Actual description from database
test_description = '''<img align="right" alt="Saudi Crown Prince Mohammed bin Salman makes his way to greet US President Donald Trump upon his arrival in Riyadh, Saudi Arabia, May 13, 2025 (photo credit: BRENDAN SMIALOWSKI/AFP via Getty Images)" src="https://images.jpost.com/image/upload/f_auto,fl_lossy/q_auto/c_fill,g_faces:center,h_537,w_822/710007" title="Saudi Crown Prince Mohammed bin Salman makes his way to greet US President Donald Trump upon his arrival in Riyadh, Saudi Arabia, May 13, 2025 (photo credit: BRE">'''

print("=" * 80)
print("TESTING WITH ACTUAL JPOST IMAGE")
print("=" * 80)

print("\nORIGINAL:")
print(test_description[:300])

result = sanitize_html_content(test_description)

print("\n\nSANITIZED OUTPUT:")
print(result)

print("\n\n" + "=" * 80)
print("ANALYSIS")
print("=" * 80)

if '<img' in result:
    print("✅ Image tag preserved")
    
if 'alt=' in result:
    print("⚠️ WARNING: alt attribute present (contains long caption text)")
    # Extract alt text
    import re
    alt_match = re.search(r'alt="([^"]*)"', result)
    if alt_match:
        alt_text = alt_match.group(1)
        print(f"   Alt text length: {len(alt_text)} characters")
        print(f"   Alt text preview: {alt_text[:80]}...")

if 'title=' in result:
    print("⚠️ WARNING: title attribute present (contains long caption text)")

print("\nSuggestion: Remove or truncate alt/title attributes for images")
