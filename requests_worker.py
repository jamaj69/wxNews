#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP fetcher worker — plain ``requests`` library.

Spawned by ``article_fetcher._RequestsFetcher._make_process()``.
Kept intentionally thin: all heavy imports happen inside ``worker()``.

Protocol
--------
request:  ``(req_id: str, url: str, timeout: int)``
        | ``None``   ← shutdown sentinel
response: ``(req_id: str, result: dict)``

result keys: html, success, error_code, error_type
"""

import multiprocessing
import signal

# Error-type constants (mirrored from article_fetcher to keep this module standalone)
ERROR_PERMANENT = 'permanent'
ERROR_TEMPORARY = 'temporary'

_PERMANENT_HTTP_CODES = frozenset({401, 402, 403, 404, 406, 410, 451})


def _classify(status: int) -> str:
    return ERROR_PERMANENT if status in _PERMANENT_HTTP_CODES else ERROR_TEMPORARY


def _decode(response) -> str:
    # Prefer apparent_encoding (chardet/charset-normalizer) when it disagrees
    # with the declared encoding.  This handles servers that send charset=utf-8
    # in their Content-Type but actually serve cp1251 or other legacy encodings
    # (common on Russian news sites such as interfax.ru / sport-interfax.ru).
    # response.text uses errors='replace' so it never raises but silently
    # produces garbled output for such mismatches.
    declared = (response.encoding or '').lower().strip()
    apparent = (response.apparent_encoding or '').lower().strip()
    if apparent and apparent not in ('ascii', declared):
        try:
            return response.content.decode(response.apparent_encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    try:
        return response.text
    except (UnicodeDecodeError, LookupError):
        for enc in ('utf-8', 'cp1251', 'latin-1', 'iso-8859-1', 'cp1252'):
            try:
                return response.content.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return response.content.decode('utf-8', errors='ignore')


_DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.8,en-US;q=0.5,en;q=0.3',
    'Referer': 'https://www.google.com/',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'cross-site',
    'DNT': '1',
}

_NDTV_HEADERS = {
    'User-Agent': 'FeedReader/1.0 (Linux)',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Referer': 'https://www.ndtvprofit.com/',
    'Connection': 'keep-alive',
}


def _headers_for(url: str) -> dict:
    if 'ndtvprofit.com' in url.lower():
        return _NDTV_HEADERS.copy()
    return _DEFAULT_HEADERS.copy()


def _fetch(url: str, timeout: int) -> dict:
    out = {'html': None, 'success': False, 'error_code': None, 'error_type': None}
    try:
        import requests
        resp = requests.get(url, headers=_headers_for(url), timeout=timeout)
        resp.raise_for_status()
        out['html']    = _decode(resp)
        out['success'] = True
        print(f"[requests-worker] OK {url[:80]}", flush=True)
    except Exception as e:
        import requests as _req
        if isinstance(e, _req.HTTPError):
            resp = getattr(e, 'response', None)
            code = getattr(resp, 'status_code', None)
            out['error_code'] = code
            out['error_type'] = _classify(code) if isinstance(code, int) else ERROR_TEMPORARY
        elif isinstance(e, _req.Timeout):
            out['error_code'] = 'TIMEOUT'
            out['error_type'] = ERROR_TEMPORARY
        elif isinstance(e, _req.ConnectionError):
            out['error_code'] = 'CONNECTION_ERROR'
            out['error_type'] = ERROR_TEMPORARY
        elif isinstance(e, _req.RequestException):
            out['error_code'] = 'REQUEST_ERROR'
            out['error_type'] = ERROR_TEMPORARY
        else:
            out['error_code'] = 'ERROR'
            out['error_type'] = ERROR_TEMPORARY
        print(f"[requests-worker] {type(e).__name__} ({out['error_code']}) {url[:80]}", flush=True)
    return out


def worker(
    req_q: "multiprocessing.Queue",
    resp_q: "multiprocessing.Queue",
) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    print("[requests-worker] Ready", flush=True)

    while True:
        try:
            item = req_q.get()
        except (EOFError, OSError):
            break
        if item is None:
            break
        req_id, url, timeout = item[0], item[1], item[2]
        result = _fetch(url, timeout)
        resp_q.put((req_id, result))
