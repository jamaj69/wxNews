#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless-browser fetcher worker — Playwright / Chromium.

Used for JS-rendered pages and sites that block plain HTTP clients.
Images and fonts are disabled via Chromium launch flags (no page.route()
handlers) to avoid asyncio CancelledError cascades when navigation times out.

Spawned by ``article_fetcher._PlaywrightFetcher._make_process()``.

Protocol
--------
request:  ``(req_id: str, url: str, timeout: int)``
        | ``None``   ← shutdown sentinel
response: ``(req_id: str, result: dict)``

result keys: html, success, error_code, error_type
"""

import multiprocessing
import re as _re
import signal

ERROR_PERMANENT = 'permanent'
ERROR_TEMPORARY = 'temporary'

_PERMANENT_HTTP_CODES = frozenset({401, 402, 403, 404, 406, 410, 451})


def _classify(status: int) -> str:
    return ERROR_PERMANENT if status in _PERMANENT_HTTP_CODES else ERROR_TEMPORARY


def _count_paragraphs(html: str) -> int:
    """Count non-trivial paragraphs without BeautifulSoup (fast regex)."""
    return sum(
        1 for m in _re.finditer(r'<p[^>]*>(.*?)</p>', html, _re.S | _re.I)
        if len(_re.sub(r'<[^>]+>', '', m.group(1)).strip()) > 50
    )


def _fetch(url: str, timeout_s: int, options: dict | None = None) -> dict:
    """Fetch *url* using a fresh headless Chromium instance."""
    out = {'html': None, 'success': False, 'error_code': None, 'error_type': None}
    opts = options or {}
    nojs = opts.get('nojs', False)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    '--blink-settings=imagesEnabled=false',
                    '--disable-images',
                    '--no-sandbox',
                ],
            )
            try:
                context = browser.new_context(
                    user_agent=(
                        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
                    ),
                    locale='pt-BR',
                    java_script_enabled=not nojs,
                    extra_http_headers={'Referer': 'https://www.google.com/'},
                )
                page = context.new_page()
                response = page.goto(
                    url,
                    wait_until='domcontentloaded',
                    timeout=timeout_s * 1000,
                )
                status = response.status if response else None
                if status and status >= 400:
                    out['error_code'] = status
                    out['error_type'] = _classify(status)
                    print(f"[playwright-worker] HTTP {status} {url[:80]}", flush=True)
                else:
                    if nojs:
                        # No JS → SSR content is final, capture immediately
                        out['html']    = page.content()
                        out['success'] = True
                        print(f"[playwright-worker] OK (nojs) {url[:80]}", flush=True)
                    else:
                        # Capture fast (SSR content, before paywall JS fires)
                        html_fast = page.content()
                        # Capture slow (after JS executes — needed for SPA/lazy content)
                        page.wait_for_timeout(1500)
                        html_slow = page.content()
                        # Use whichever version has more substantive paragraphs.
                        # If paywall JS fires and hides content, html_fast wins.
                        # If content is lazy-loaded, html_slow wins.
                        fast_p = _count_paragraphs(html_fast)
                        slow_p = _count_paragraphs(html_slow)
                        out['html']    = html_fast if fast_p > slow_p else html_slow
                        out['success'] = True
                        print(f"[playwright-worker] OK (fast={fast_p}/slow={slow_p}) {url[:80]}", flush=True)
            finally:
                browser.close()

    except ImportError as e:
        out['error_code'] = 'UNAVAILABLE'
        out['error_type'] = ERROR_TEMPORARY
        print(f"[playwright-worker] playwright not installed: {e}", flush=True)
    except Exception as e:
        name = type(e).__name__
        msg  = str(e)
        if 'Timeout' in name or 'timeout' in msg.lower():
            out['error_code'] = 'TIMEOUT'
            out['error_type'] = ERROR_TEMPORARY
        elif 'net::ERR_' in msg or 'ConnectionRefused' in name:
            out['error_code'] = 'CONNECTION_ERROR'
            out['error_type'] = ERROR_TEMPORARY
        else:
            out['error_code'] = 'BROWSER_ERROR'
            out['error_type'] = ERROR_TEMPORARY
        print(f"[playwright-worker] {name} ({out['error_code']}) {url[:80]}: {msg[:120]}", flush=True)

    return out


def worker(
    req_q: "multiprocessing.Queue",
    resp_q: "multiprocessing.Queue",
) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        print("[playwright-worker] Ready", flush=True)
    except ImportError as e:
        print(f"[playwright-worker] playwright not installed: {e}", flush=True)
        while True:
            try:
                item = req_q.get()
            except (EOFError, OSError):
                return
            if item is None:
                return
            req_id, *_ = item
            resp_q.put((req_id, {
                'html': None, 'success': False,
                'error_code': 'UNAVAILABLE', 'error_type': ERROR_TEMPORARY,
            }))
        return

    while True:
        try:
            item = req_q.get()
        except (EOFError, OSError):
            break
        if item is None:
            break
        req_id, url, timeout_s = item[0], item[1], item[2]
        options = item[3] if len(item) > 3 else {}
        result = _fetch(url, timeout_s, options)
        resp_q.put((req_id, result))
