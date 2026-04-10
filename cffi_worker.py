#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP fetcher worker — ``curl_cffi`` with Chrome TLS fingerprint impersonation.

Bypasses Cloudflare and similar bot-blockers that reject connections based on
TLS JA3/JA4 fingerprints.

Spawned by ``article_fetcher._CffiFetcher._make_process()``.

Protocol
--------
request:  ``(req_id: str, url: str, timeout: int)``
        | ``None``   ← shutdown sentinel
response: ``(req_id: str, result: dict)``

result keys: html, success, error_code, error_type
"""

import multiprocessing
import signal

ERROR_PERMANENT = 'permanent'
ERROR_TEMPORARY = 'temporary'

_PERMANENT_HTTP_CODES = frozenset({401, 402, 403, 404, 406, 410, 451})


def _classify(status: int) -> str:
    return ERROR_PERMANENT if status in _PERMANENT_HTTP_CODES else ERROR_TEMPORARY


def _decode(response) -> str:
    try:
        return response.text
    except (UnicodeDecodeError, LookupError):
        for enc in ('utf-8', 'latin-1', 'iso-8859-1', 'cp1252'):
            try:
                return response.content.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return response.content.decode('utf-8', errors='ignore')


def _fetch(url: str, timeout: int) -> dict:
    out = {'html': None, 'success': False, 'error_code': None, 'error_type': None}
    try:
        import curl_cffi.requests as cffi_req
        from curl_cffi.requests import exceptions as cffi_exc

        resp = cffi_req.get(
            url,
            impersonate='chrome120',
            headers={
                'Accept-Language': 'pt-BR,pt;q=0.8,en-US;q=0.5,en;q=0.3',
                'Referer': 'https://www.google.com/',
                'Sec-Fetch-Site': 'cross-site',
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        out['html']    = _decode(resp)
        out['success'] = True
        print(f"[cffi-worker] OK {url[:80]}", flush=True)
    except ImportError as e:
        out['error_code'] = 'UNAVAILABLE'
        out['error_type'] = ERROR_TEMPORARY
        print(f"[cffi-worker] curl_cffi not available: {e}", flush=True)
    except Exception as e:
        # Re-import to catch cffi exceptions by type at runtime
        try:
            from curl_cffi.requests import exceptions as cffi_exc
            if isinstance(e, cffi_exc.HTTPError):
                resp = getattr(e, 'response', None)
                code = getattr(resp, 'status_code', None)
                out['error_code'] = code
                out['error_type'] = _classify(code) if isinstance(code, int) else ERROR_TEMPORARY
            elif isinstance(e, cffi_exc.Timeout):
                out['error_code'] = 'TIMEOUT'
                out['error_type'] = ERROR_TEMPORARY
            elif isinstance(e, cffi_exc.RequestException):
                out['error_code'] = 'REQUEST_ERROR'
                out['error_type'] = ERROR_TEMPORARY
            else:
                out['error_code'] = 'ERROR'
                out['error_type'] = ERROR_TEMPORARY
        except ImportError:
            out['error_code'] = 'ERROR'
            out['error_type'] = ERROR_TEMPORARY
        print(f"[cffi-worker] {type(e).__name__} ({out['error_code']}) {url[:80]}", flush=True)
    return out


def worker(
    req_q: "multiprocessing.Queue",
    resp_q: "multiprocessing.Queue",
) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # Verify availability at start-up
    try:
        import curl_cffi.requests  # noqa: F401
        print("[cffi-worker] Ready", flush=True)
    except ImportError as e:
        print(f"[cffi-worker] curl_cffi not installed: {e}", flush=True)
        # Stay alive and return UNAVAILABLE for all requests so the
        # orchestrator can fall back gracefully
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
        req_id, url, timeout = item[0], item[1], item[2]
        result = _fetch(url, timeout)
        resp_q.put((req_id, result))
