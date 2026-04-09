#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Text processing utilities shared across translation modules.
"""

import re

# Maximum characters sent per Google Translate API call.
MAX_TRANSLATE_CHARS = 4500


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
