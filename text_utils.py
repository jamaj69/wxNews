#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Text processing utilities shared across translation modules.
"""

import re

# Maximum characters sent per NLLB request (tokenizer truncates at 512 tokens anyway).
MAX_TRANSLATE_CHARS = 4500

# Safe limit per Google Translate request (free API cap is 5000 chars).
GOOGLE_MAX_CHARS = 4900


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
