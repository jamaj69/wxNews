#!/usr/bin/env python3
"""
monitor_rss.py — Monitora a dinâmica do RSS fetcher em tempo real.

Uso:
    python3 monitor_rss.py [--interval SEGUNDOS] [--url URL_BASE]

Exemplos:
    python3 monitor_rss.py
    python3 monitor_rss.py --interval 5
    python3 monitor_rss.py --url http://localhost:8765
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any


# ─── ANSI colours ─────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
CYAN    = "\033[36m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
MAGENTA = "\033[35m"
WHITE   = "\033[97m"
BG_BLUE = "\033[44m"
BG_RED  = "\033[41m"

def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"

def _pct(a: int, b: int) -> str:
    if b <= 0:
        return "  —%"
    return f"{a/b*100:5.1f}%"


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def fetch_json(url: str, timeout: float = 5.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as err:
        return {"_error": str(err)}


# ─── State ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Sample:
    ts:   float
    rss:  dict[str, Any]


def _get(d: dict, *keys: str, default: Any = 0) -> Any:
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d if d is not None else default


# ─── Spark history bar ────────────────────────────────────────────────────────

_SPARK = " ▁▂▃▄▅▆▇█"

def _spark(history: deque) -> str:
    """Tiny sparkline of done-per-sample delta."""
    vals = list(history)
    if not vals:
        return ""
    mx = max(vals) or 1
    return "".join(_SPARK[min(int(v / mx * 8), 8)] for v in vals)


# ─── Progress bar ─────────────────────────────────────────────────────────────

def _bar(done: int, total: int, width: int = 36) -> str:
    if total <= 0:
        return _c(DIM, "─" * width)
    pct   = min(done / total, 1.0)
    filled = int(pct * width)
    bar    = "█" * filled + "░" * (width - filled)
    color  = GREEN if pct >= 1.0 else CYAN
    return f"{_c(color, bar[:filled])}{_c(DIM, bar[filled:])}"


# ─── Display ──────────────────────────────────────────────────────────────────

def print_snapshot(
    samples:      deque,
    speed_history: deque,
    interval_s:   float,
    seq:          int,
) -> None:
    cur  = samples[-1]
    prev = samples[-2] if len(samples) >= 2 else None

    now_str = datetime.now().strftime("%H:%M:%S")
    r       = cur.rss

    # ── error guard ──────────────────────────────────────────────────────────
    if not r:
        print(_c(RED, f"\n[{now_str}] Sem dados RSS no endpoint."))
        return

    # ── base values ──────────────────────────────────────────────────────────
    status        = r.get("status", "?")
    cycle         = r.get("cycle", 0)
    total         = r.get("total", 0)
    done          = r.get("done", 0)          # stage-1 completions
    pending       = r.get("pending", 0)       # stage-1 still queued
    running       = r.get("running", 0)       # stage-1 under semaphore
    queued        = r.get("queued", 0)        # feeds handed to stage-2 queue (cumulative)
    processed     = r.get("processed", 0)     # stage-2 completions
    ok            = r.get("ok", 0)
    err_http      = r.get("err_http", 0)
    err_content   = r.get("err_content", 0)
    err_timeout   = r.get("err_timeout", 0)
    articles_new  = r.get("articles_new", 0)
    elapsed_s     = r.get("elapsed_s") or 0.0
    next_in_s     = r.get("next_cycle_in_s")
    started_at    = r.get("started_at", "—")

    # items still in queue (best-effort estimate)
    queue_depth   = max(0, queued - processed)

    # ── deltas vs previous sample ─────────────────────────────────────────────
    elapsed_delta = (cur.ts - prev.ts) if prev else interval_s

    def delta(key: str) -> int:
        if prev is None:
            return 0
        return r.get(key, 0) - prev.rss.get(key, 0)

    d_done      = delta("done")
    d_processed = delta("processed")
    d_art       = delta("articles_new")
    d_timeout   = delta("err_timeout")

    # stage-1 cycle average throughput (feeds/s)
    cycle_rate_s1 = done / elapsed_s if elapsed_s > 0 else 0.0
    # stage-2 throughput over last interval
    rate_s2 = d_processed / elapsed_delta if elapsed_delta > 0 else 0.0

    # ETA
    remaining_s2 = max(0, queued - processed)
    if status == "sleeping":
        eta_str = _c(GREEN, "a dormir")
    elif remaining_s2 <= 0 and pending <= 0:
        eta_str = _c(GREEN, "completo")
    else:
        fetch_secs = (pending / cycle_rate_s1) if cycle_rate_s1 > 0 else 0
        proc_secs  = (remaining_s2 / rate_s2)  if rate_s2 > 0 else fetch_secs
        secs_left  = max(fetch_secs, proc_secs)
        if secs_left <= 0:
            eta_str = _c(DIM, "—")
        elif secs_left < 60:
            eta_str = _c(CYAN, f"~{secs_left:.0f}s")
        elif secs_left < 3600:
            eta_str = _c(YELLOW, f"~{secs_left/60:.1f}min")
        else:
            eta_str = _c(RED, f"~{secs_left/3600:.1f}h")

    # ── status colour ─────────────────────────────────────────────────────────
    if status == "running":
        status_str = _c(GREEN + BOLD, "● RUNNING")
    elif status == "sleeping":
        status_str = _c(CYAN, "◌ sleeping")
    else:
        status_str = _c(DIM, "○ idle")

    # ── clear screen & header ─────────────────────────────────────────────────
    print("\033[H\033[2J", end="")

    hdr = f" Monitor RSS Fetcher — {now_str}  (atualização #{seq}, a cada {interval_s:.0f}s) "
    print(_c(BG_BLUE + BOLD + WHITE, hdr.center(72)))
    print()

    # ── cycle info line ───────────────────────────────────────────────────────
    print(
        f"  Ciclo  {_c(BOLD, str(cycle)):>4}   "
        f"{status_str}   "
        f"iniciado {_c(DIM, started_at[11:19] if started_at and len(started_at) >= 19 else '—')}   "
        f"elapsed {_c(YELLOW, f'{elapsed_s:.0f}s'):>8}"
    )
    print()

    # ══════════════════════════════════════════════════════════════════════════
    print(_c(BOLD + CYAN, "  ── Stage 1: Fetch (HTTP + feedparser) ──────────────────────────"))
    print()

    bar_line = _bar(done, total)
    print(
        f"  Progresso  {_c(BOLD, f'{done:,}')}/{_c(DIM, str(total))}  "
        f"[{bar_line}]  {_pct(done, total)}"
    )
    print()

    running_color = GREEN if running > 0 else DIM
    print(
        f"  {'Em execução (semáforo)':<28} {_c(running_color + BOLD, f'{running:>4}')}"
        f"   {'Aguardando slot':<22} {_c(YELLOW if pending > 0 else DIM, f'{pending:>5}')}"
    )
    print()

    total_err = err_http + err_content + err_timeout
    print(
        f"  {'OK  (→ fila Stage 2)':<28} {_c(GREEN + BOLD, f'{queued:>4}')}"
        f"   {'Erros':<22} {_c(RED + BOLD if total_err else DIM, f'{total_err:>5}')}"
    )
    if total_err:
        print(
            f"    {'↳ Timeout fetch':<26} {_c(RED if err_timeout else DIM, f'{err_timeout:>4}')}"
            f"   {'↳ HTTP 4xx/5xx':<22} {_c(RED if err_http else DIM, f'{err_http:>5}')}"
        )
        if err_content:
            print(f"    {'↳ Conteúdo inválido/parse':<26} {_c(RED, f'{err_content:>4}')}")

    if d_done > 0 and prev is not None:
        rate_s1 = d_done / elapsed_delta if elapsed_delta > 0 else 0.0
        print(
            f"\n  {'Velocidade Stage 1':<28} "
            f"{_c(CYAN, f'{cycle_rate_s1:.2f} f/s')} média ciclo   "
            f"{_c(CYAN, f'{rate_s1:.2f} f/s')} últimos {elapsed_delta:.0f}s"
        )

    print()

    # ══════════════════════════════════════════════════════════════════════════
    MAGENTA = "\033[35m"
    print(_c(BOLD + MAGENTA, "  ── Stage 2: Process (dedup → insert DB) ────────────────────────"))
    print()

    proc_bar = _bar(processed, queued)
    print(
        f"  Progresso  {_c(BOLD, f'{processed:,}')}/{_c(DIM, str(queued))}  "
        f"[{proc_bar}]  {_pct(processed, queued)}"
    )
    print()

    q_color = YELLOW if queue_depth > 0 else DIM
    print(
        f"  {'Na fila (aguardando)':<28} {_c(q_color + BOLD, f'{queue_depth:>4}')}"
        f"   {'Processados':<22} {_c(GREEN, f'{processed:>5}')}"
    )
    print()

    art_color = GREEN + BOLD if articles_new > 0 else DIM
    print(
        f"  {'Artigos novos (ciclo)':<28} {_c(art_color, f'{articles_new:>4}')}"
        + (f"   {_c(GREEN, f'+{d_art}')} neste intervalo" if d_art > 0 else "")
    )
    if rate_s2 > 0.05 and prev is not None:
        print(f"  {'Velocidade Stage 2':<28} {_c(MAGENTA, f'{rate_s2:.2f} f/s')}")

    speed_history.append(d_processed)
    if len(speed_history) >= 3:
        print(f"\n  Hist. Stage 2  {_c(DIM, _spark(speed_history))}")

    print()

    # ── ETA / next cycle ─────────────────────────────────────────────────────
    print(_c(BOLD, "  ── Tempo ────────────────────────────────────────────────────────"))
    print(f"  {'ETA conclusão do ciclo':<28} {eta_str}")
    if next_in_s is not None:
        mins, secs = divmod(int(next_in_s), 60)
        nxt_str = f"{mins}min {secs}s" if mins else f"{secs}s"
        print(f"  {'Próximo ciclo em':<28} {_c(CYAN, nxt_str)}")
    print()
    print(_c(DIM, "  Ctrl+C para sair"))


# ─── Main loop ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor RSS Fetcher")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Intervalo de atualização em segundos (default: 5)")
    parser.add_argument("--url", default="http://localhost:8765",
                        help="URL base da API (default: http://localhost:8765)")
    args = parser.parse_args()

    endpoint      = args.url.rstrip("/") + "/api/queues"
    interval_s    = max(1.0, args.interval)
    samples       = deque(maxlen=60)
    speed_history = deque(maxlen=30)
    seq           = 0

    print(f"Conectando a {endpoint} ...")

    try:
        while True:
            data = fetch_json(endpoint)
            if data and "_error" not in data:
                rss_data = data.get("rss", {})
            else:
                rss_data = {}

            samples.append(Sample(ts=time.monotonic(), rss=rss_data))
            seq += 1

            if "_error" in (data or {}):
                print(_c(RED, f"[{datetime.now().strftime('%H:%M:%S')}] Erro: {data['_error']}"))
            else:
                print_snapshot(samples, speed_history, interval_s, seq)

            time.sleep(interval_s)

    except KeyboardInterrupt:
        print("\nMonitor encerrado.")
        sys.exit(0)


if __name__ == "__main__":
    main()
