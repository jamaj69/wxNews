#!/usr/bin/env python3
"""
monitor_queues.py — Monitora as filas do wxAsyncNewsGather em tempo real.

Uso:
    python3 monitor_queues.py [--interval SEGUNDOS] [--url URL_BASE]

Exemplos:
    python3 monitor_queues.py
    python3 monitor_queues.py --interval 15
    python3 monitor_queues.py --url http://localhost:8765
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# ─── ANSI colours ────────────────────────────────────────────────────────────
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

def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"

def _sign(n: int | float) -> str:
    """Format number with explicit + or – sign."""
    if n > 0:
        return _c(GREEN, f"+{n:,}")
    elif n < 0:
        return _c(RED, f"{n:,}")
    return _c(DIM, "0")

def _rate(per_min: float | None) -> str:
    if per_min is None:
        return _c(DIM, "  —  /min")
    if per_min > 0:
        return _c(GREEN, f"+{per_min:6.1f}/min")
    elif per_min < 0:
        return _c(RED, f"{per_min:6.1f}/min")
    return _c(DIM, f"  0.0/min")

def _eta(pending: int, rate_per_min: float | None) -> str:
    """Return human-readable ETA for a queue to drain at the given rate."""
    if pending <= 0:
        return _c(GREEN, "completo")
    if not rate_per_min or rate_per_min >= 0:
        return _c(DIM, "—")
    # rate_per_min is negative (pending decreasing)
    mins = pending / abs(rate_per_min)
    if mins < 60:
        return _c(YELLOW, f"~{mins:.0f}min")
    hours = mins / 60
    if hours < 48:
        return _c(YELLOW, f"~{hours:.1f}h")
    days = hours / 24
    return _c(RED, f"~{days:.1f}d")

def _bar(value: int, total: int, width: int = 30) -> str:
    if total <= 0:
        return "[" + "?" * width + "]"
    pct = min(value / total, 1.0)
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{_c(CYAN, bar[:filled])}{_c(DIM, bar[filled:])}] {pct*100:5.1f}%"


# ─── HTTP helper ─────────────────────────────────────────────────────────────

def fetch_json(url: str, timeout: float = 5.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as err:
        return {"_error": str(err)}


# ─── State ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Sample:
    ts:   float
    data: dict[str, Any]

def _get(d: dict[str, Any], *keys: str, default: Any = 0) -> Any:
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d if d is not None else default


# ─── Display ─────────────────────────────────────────────────────────────────

def print_snapshot(samples: deque, first: "Sample | None", interval_s: float, seq: int) -> None:
    cur  = samples[-1]
    prev = samples[-2] if len(samples) >= 2 else None

    now_str = datetime.now().strftime("%H:%M:%S")
    elapsed = cur.ts - prev.ts if prev else interval_s

    d = cur.data
    if "_error" in d:
        print(_c(RED, f"\n[{now_str}] Erro: {d['_error']}"))
        return

    a  = d.get("articles", {})
    eq = d.get("enrichment", {})
    tq = d.get("translation", {})

    # --- helper to compute delta and rate ---
    def delta_rate(keys: list[str]):
        cur_val  = _get(d, *keys)
        if prev is None:
            return cur_val, None, None
        prev_val = _get(prev.data, *keys)
        diff     = cur_val - prev_val
        rate     = (diff / elapsed) * 60.0 if elapsed > 0 else 0.0
        return cur_val, diff, rate

    total,       d_total,  r_total  = delta_rate(["articles", "total"])
    enriched,    d_enr,    r_enr    = delta_rate(["articles", "enriched"])
    enr_pend,    d_epend,  r_epend  = delta_rate(["articles", "enrich_pending"])
    enr_fail,    d_efail,  r_efail  = delta_rate(["articles", "enrich_failed"])
    translated,  d_transl, r_transl = delta_rate(["articles", "translated"])
    t_skip,      d_tskip,  r_tskip  = delta_rate(["articles", "translate_skipped"])
    t_pend,      d_tpend,  r_tpend  = delta_rate(["translation", "pending_db"])
    in_flight,   d_ifl,    r_ifl    = delta_rate(["enrichment", "in_flight"])
    worker_q,    _,        _        = delta_rate(["enrichment", "worker_queue"])

    stats_age = d.get("stats_age_s")
    ts_iso    = d.get("timestamp_iso", "—")

    # ── Header ──────────────────────────────────────────────────────────────
    print()
    header = f" Monitor de Filas — {now_str}  (ciclo #{seq}, intervalo {interval_s:.0f}s) "
    print(_c(BG_BLUE + BOLD + WHITE, header.center(72)))

    # ── Artigos totais ───────────────────────────────────────────────────────
    print(f"\n  {_c(BOLD, 'ARTIGOS TOTAIS')}")
    print(f"    Total no DB  : {_c(BOLD+WHITE, f'{total:>10,}')}  {_sign(d_total) if d_total is not None else ''}  {_rate(r_total)}")

    # ── Enriquecimento ───────────────────────────────────────────────────────
    print(f"\n  {_c(BOLD, 'ENRIQUECIMENTO')}")
    print(f"    Enriquecidos : {_c(BOLD+GREEN, f'{enriched:>10,}')}  {_sign(d_enr) if d_enr is not None else ''}  {_rate(r_enr)}")
    print(f"    Pendentes    : {_c(BOLD+YELLOW, f'{enr_pend:>10,}')}  {_sign(d_epend) if d_epend is not None else ''}  {_rate(r_epend)}  ETA {_eta(enr_pend, r_epend)}")
    print(f"    Falhas       : {_c(RED, f'{enr_fail:>10,}')}  {_sign(d_efail) if d_efail is not None else ''}  {_rate(r_efail)}")
    if total > 0:
        print(f"    Progresso    : {_bar(enriched, total)}")
    print(f"    Worker fila  : {_c(CYAN, f'{worker_q:>10,}')}   em voo: {_c(CYAN, str(in_flight))}  {_sign(d_ifl) if d_ifl is not None else ''}")

    # ── Por tier de enriquecimento ───────────────────────────────────────────
    tiers: list[dict] = _get(d, "enrichment", "tiers", default=[])
    if tiers:
        _BACKEND_COLOR = {'cffi': CYAN, 'requests': MAGENTA, 'playwright': YELLOW}
        print(f"\n  {_c(BOLD, 'TIERS DE ENRIQUECIMENTO')}")
        hdr = f"    {'Backend':<12}  {'Pendente':>9}  {'Em Voo':>7}  {'Resolvido':>9}  {'Avançado':>9}  {'Descartado':>10}"
        print(_c(DIM, hdr))
        print(_c(DIM, "    " + "─" * 66))
        for tier in tiers:
            backend  = tier.get("backend", "?")
            col      = _BACKEND_COLOR.get(backend, WHITE)
            pending  = tier.get("pending",  0)
            in_fl    = tier.get("in_flight", 0)
            resolved = tier.get("resolved", 0)
            advanced = tier.get("advanced", 0)
            gave_up  = tier.get("gave_up",  0)
            print(
                f"    {_c(col+BOLD, f'{backend:<12}')}"
                f"  {_c(YELLOW, f'{pending:>9,}')}"
                f"  {_c(CYAN,   f'{in_fl:>7,}')}"
                f"  {_c(GREEN,  f'{resolved:>9,}')}"
                f"  {_c(DIM,    f'{advanced:>9,}')}"
                f"  {_c(RED,    f'{gave_up:>10,}')}"
            )

    # ── Tradução ─────────────────────────────────────────────────────────────
    print(f"\n  {_c(BOLD, 'TRADUÇÃO')}")
    print(f"    Traduzidos   : {_c(BOLD+GREEN, f'{translated:>10,}')}  {_sign(d_transl) if d_transl is not None else ''}  {_rate(r_transl)}")
    print(f"    Ignorados    : {_c(DIM, f'{t_skip:>10,}')}  {_sign(d_tskip) if d_tskip is not None else ''}  {_rate(r_tskip)}")
    print(f"    Pendentes    : {_c(BOLD+YELLOW, f'{t_pend:>10,}')}  {_sign(d_tpend) if d_tpend is not None else ''}  {_rate(r_tpend)}  ETA {_eta(t_pend, r_tpend)}")
    if total > 0:
        print(f"    Progresso    : {_bar(translated, total)}")

    # ── Velocidades: janela recente + sessão completa ────────────────────────
    def _span_rate(a: "Sample", b: "Sample", keys: list[str]) -> float | None:
        span = b.ts - a.ts
        if span <= 0:
            return None
        return (_get(b.data, *keys) - _get(a.data, *keys)) / span * 60.0

    rows: list[tuple[str, float | None, float | None, float | None]] = []

    # Linha 1: janela recente (deque)
    if len(samples) >= 3:
        oldest  = samples[0]
        span_w  = cur.ts - oldest.ts
        n_w     = len(samples) - 1
        label_w = f"janela {n_w} amostras ({span_w/60:.1f}min)"
        rows.append((
            label_w,
            _span_rate(oldest, cur, ["articles", "total"]),
            _span_rate(oldest, cur, ["articles", "enriched"]),
            _span_rate(oldest, cur, ["articles", "translated"]),
        ))

    # Linha 2: sessão completa (desde o início)
    sess_rt: float | None = None
    sess_re: float | None = None
    if first is not None and first is not cur:
        span_s  = cur.ts - first.ts
        label_s = f"sessão completa ({span_s/60:.1f}min)"
        sess_rt = _span_rate(first, cur, ["articles", "total"])
        sess_re = _span_rate(first, cur, ["articles", "enriched"])
        sess_rtr = _span_rate(first, cur, ["articles", "translated"])
        rows.append((label_s, sess_rt, sess_re, sess_rtr))

    if rows:
        print(f"\n  {_c(BOLD, 'VELOCIDADES MÉDIAS')}")
        hdr = f"    {'Janela':<32}  {'Chegadas':>12}  {'Enriquecidas':>14}  {'Traduzidas':>12}"
        print(_c(DIM, hdr))
        print(_c(DIM, "    " + "─" * 76))
        for label, rt, re, rtr in rows:
            print(
                f"    {_c(DIM, f'{label:<32}')}"
                f"  {_rate(rt):>12}"
                f"  {_rate(re):>14}"
                f"  {_rate(rtr):>12}"
            )

    # ── ETA global de enriquecimento (média da sessão) ───────────────────────
    if sess_rt is not None and sess_re is not None and enr_pend > 0:
        net = (sess_re or 0) - (sess_rt or 0)   # líquido: enriquece mais do que chega?
        if net > 0:
            mins = enr_pend / net
            if mins < 60:
                eta_global = _c(GREEN, f"~{mins:.0f}min")
            elif mins / 60 < 48:
                eta_global = _c(YELLOW, f"~{mins/60:.1f}h")
            else:
                eta_global = _c(RED, f"~{mins/60/24:.1f}d")
            print(
                f"\n  {_c(BOLD, 'ETA ENRIQUECIMENTO')}  "
                f"(ritmo líquido sessão: {_rate(net)})  →  {eta_global}"
            )
        else:
            print(
                f"\n  {_c(BOLD, 'ETA ENRIQUECIMENTO')}  "
                f"{_c(RED, 'chegadas superam enriquecimentos')}  "
                f"(líquido: {_rate(net)})"
            )

    # ── Rodapé ───────────────────────────────────────────────────────────────
    age_str = f"{stats_age}s" if stats_age is not None else "—"
    print(_c(DIM, f"\n  última actualiz. cache: {age_str}   ts: {ts_iso}"))


# ─── Main loop ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", "-i", type=float, default=30.0,
                        help="Intervalo entre amostras em segundos (padrão: 30)")
    parser.add_argument("--url", "-u", default="http://localhost:8765",
                        help="URL base da API (padrão: http://localhost:8765)")
    parser.add_argument("--history", type=int, default=10,
                        help="Número de amostras a manter para média (padrão: 10)")
    args = parser.parse_args()

    base_url    = args.url.rstrip("/")
    queues_url  = f"{base_url}/api/queues"
    interval_s  = args.interval
    max_history = max(2, args.history)

    samples: deque[Sample] = deque(maxlen=max_history)
    first_sample: Sample | None = None
    seq = 0

    print(_c(BOLD, f"Iniciando monitor · {queues_url} · intervalo={interval_s}s"))
    print(_c(DIM, "Ctrl+C para sair\n"))

    try:
        while True:
            t0   = time.monotonic()
            data = fetch_json(queues_url)
            ts   = time.time()
            seq += 1

            s = Sample(ts, data)
            samples.append(s)
            if first_sample is None and "_error" not in data:
                first_sample = s
            print_snapshot(samples, first_sample, interval_s, seq)

            elapsed = time.monotonic() - t0
            sleep_s = max(0.0, interval_s - elapsed)
            time.sleep(sleep_s)

    except KeyboardInterrupt:
        print(_c(DIM, "\n\nMonitor encerrado."))
        sys.exit(0)


if __name__ == "__main__":
    main()
