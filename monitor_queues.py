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

def print_snapshot(
    samples: deque,
    first: "Sample | None",
    wm_pending: int | None,
    wm_ts: float | None,
    interval_s: float,
    seq: int,
) -> None:
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
    in_flight_note = f"  ({_c(CYAN, str(in_flight))} em voo)" if in_flight else ""
    enr_sum = enriched + enr_pend + enr_fail
    chk_enr_col = GREEN if enr_sum == total else RED
    chk_enr = "✓" if enr_sum == total else f"✗ soma={enr_sum:,} ≠ total={total:,}"
    print(f"\n  {_c(BOLD, 'ENRIQUECIMENTO')}")
    print(f"    Enriquecidos : {_c(BOLD+GREEN, f'{enriched:>10,}')}  {_sign(d_enr) if d_enr is not None else ''}  {_rate(r_enr)}")
    print(f"    Pendentes    : {_c(BOLD+YELLOW, f'{enr_pend:>10,}')}  {_sign(d_epend) if d_epend is not None else ''}  {_rate(r_epend)}{in_flight_note}  ETA {_eta(enr_pend, r_epend)}")
    print(f"    Falhas       : {_c(RED, f'{enr_fail:>10,}')}  {_sign(d_efail) if d_efail is not None else ''}  {_rate(r_efail)}")
    print(_c(DIM, f"    {'─'*54}"))
    print(f"    {'Total DB':<13}: {_c(chk_enr_col+BOLD, f'{enr_sum:>10,}')}  {_c(chk_enr_col, chk_enr)}")
    if worker_q:
        print(f"    Fila worker  : {_c(DIM, f'{worker_q:>10,}')}")

    # ── Por tier de enriquecimento ───────────────────────────────────────────
    tiers: list[dict] = _get(d, "enrichment", "tiers", default=[])
    if tiers:
        _BACKEND_COLOR = {'cffi': CYAN, 'requests': MAGENTA, 'playwright': YELLOW}
        print(f"\n  {_c(BOLD, 'TIERS DE ENRIQUECIMENTO')}  {_c(DIM, '(acumulado desde início do serviço)')}")
        hdr = f"    {'Backend':<12}  {'Pendente':>9}  {'Resolvido':>9}  {'Avançado':>9}  {'Desistiu':>9}"
        print(_c(DIM, hdr))
        print(_c(DIM, "    " + "─" * 53))
        for tier in tiers:
            backend  = tier.get("backend", "?")
            col      = _BACKEND_COLOR.get(backend, WHITE)
            pending  = tier.get("pending",  0)
            resolved = tier.get("resolved", 0)
            advanced = tier.get("advanced", 0)
            gave_up  = tier.get("gave_up",  0)
            col_p = RED if backend.startswith("stale") else YELLOW
            print(
                f"    {_c(col+BOLD, f'{backend:<12}')}"
                f"  {_c(col_p,  f'{pending:>9,}')}"
                f"  {_c(GREEN,  f'{resolved:>9,}')}"
                f"  {_c(DIM,    f'{advanced:>9,}')}"
                f"  {_c(RED,    f'{gave_up:>9,}')}"
            )
        tier_pend_sum = sum(t.get("pending", 0) for t in tiers)
        print(_c(DIM, f"    {'─'*53}"))
        chk_col = GREEN if tier_pend_sum == enr_pend else RED
        chk_msg = "✓" if tier_pend_sum == enr_pend else f"✗ tiers={tier_pend_sum:,} ≠ enrich_pending={enr_pend:,}"
        print(f"    {'Total tiers':<12}  {_c(chk_col+BOLD, f'{tier_pend_sum:>9,}')}  {_c(chk_col, chk_msg)}")

    # ── Tradução ─────────────────────────────────────────────────────────────
    t_not_eligible = max(0, total - translated - t_skip - t_pend)
    tran_sum = translated + t_skip + t_pend + t_not_eligible
    chk_tran_col = GREEN if tran_sum == total else RED
    chk_tran = "✓" if tran_sum == total else f"✗ soma={tran_sum:,} ≠ total={total:,}"
    print(f"\n  {_c(BOLD, 'TRADUÇÃO')}")
    print(f"    Traduzidos   : {_c(BOLD+GREEN, f'{translated:>10,}')}  {_sign(d_transl) if d_transl is not None else ''}  {_rate(r_transl)}")
    print(f"    Ignorados    : {_c(DIM, f'{t_skip:>10,}')}  {_sign(d_tskip) if d_tskip is not None else ''}  {_rate(r_tskip)}")
    print(f"    Pendentes    : {_c(BOLD+YELLOW, f'{t_pend:>10,}')}  {_sign(d_tpend) if d_tpend is not None else ''}  {_rate(r_tpend)}  ETA {_eta(t_pend, r_tpend)}")
    print(f"    Não elegível : {_c(DIM, f'{t_not_eligible:>10,}')}  {_c(DIM, '(aguardam enriquecimento ou idioma sem tradução)')}")
    print(_c(DIM, f"    {'─'*54}"))
    print(f"    {'Total DB':<13}: {_c(chk_tran_col+BOLD, f'{tran_sum:>10,}')}  {_c(chk_tran_col, chk_tran)}")

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
    def _fmt_eta(mins: float) -> str:
        if mins < 60:
            return _c(GREEN, f"~{mins:.0f}min")
        elif mins / 60 < 48:
            return _c(YELLOW, f"~{mins/60:.1f}h")
        return _c(RED, f"~{mins/60/24:.1f}d")

    has_eta = False
    if sess_rt is not None and sess_re is not None and enr_pend > 0:
        net = (sess_re or 0) - (sess_rt or 0)
        if net > 0:
            eta_sessao = _fmt_eta(enr_pend / net)
            label_eta1 = _c(DIM, f"sessão ({_rate(net)} líq.)")
        else:
            eta_sessao = _c(RED, "∞  (chegadas ≥ enriquecidas)")
            label_eta1 = _c(DIM, f"sessão ({_rate(net)} líq.)")
        has_eta = True
    else:
        eta_sessao = _c(DIM, "—")
        label_eta1 = _c(DIM, "sessão")

    # ── ETA por marca-d'água (drain real, ignora bursts de chegadas) ─────────
    cur_pend = enr_pend
    if (
        wm_pending is not None and wm_ts is not None
        and wm_pending > cur_pend
        and cur.ts > wm_ts
    ):
        drain_span  = cur.ts - wm_ts          # segundos desde o mínimo anterior
        drain_count = wm_pending - cur_pend   # artigos drenados nesse intervalo
        drain_pm    = drain_count / drain_span * 60.0
        if drain_pm > 0:
            eta_wm    = _fmt_eta(cur_pend / drain_pm)
            label_eta2 = _c(DIM, f"marca-d'água ({_rate(drain_pm)} drain)")
        else:
            eta_wm    = _c(DIM, "—")
            label_eta2 = _c(DIM, "marca-d'água")
        has_eta = True
    else:
        eta_wm    = _c(DIM, "aguardando progresso…")
        label_eta2 = _c(DIM, "marca-d'água")
        wm_info   = f"mín={wm_pending:,}" if wm_pending is not None else "—"

    if has_eta or enr_pend > 0:
        print(f"\n  {_c(BOLD, 'ETA ENRIQUECIMENTO')}")
        print(f"    {label_eta1:<50}  →  {eta_sessao}")
        print(f"    {label_eta2:<50}  →  {eta_wm}")

    # ── RSS pipeline (resumo) ─────────────────────────────────────────────────
    rss = d.get("rss", {})
    if rss:
        rss_status  = rss.get("status", "idle")
        rss_cycle   = rss.get("cycle", 0)
        rss_total   = rss.get("total", 0)
        rss_done    = rss.get("done", 0)
        rss_proc    = rss.get("processed", 0)
        rss_queued  = rss.get("queued", 0)
        rss_art     = rss.get("articles_new", 0)
        rss_elapsed = rss.get("elapsed_s") or 0.0
        rss_next    = rss.get("next_cycle_in_s")
        s2_workers  = rss.get("stage2_workers", 0)
        s1s2_depth  = rss.get("s1s2_depth", 0)
        s2s3_depth  = rss.get("s2s3_depth", 0)
        err_total   = rss.get("err_http", 0) + rss.get("err_content", 0) + rss.get("err_timeout", 0)

        if rss_status == "running":
            rss_status_str = _c(GREEN + BOLD, "● RUNNING")
        elif rss_status == "sleeping":
            nxt = f"  (próximo em {rss_next:.0f}s)" if rss_next else ""
            rss_status_str = _c(CYAN, f"◌ sleeping{nxt}")
        else:
            rss_status_str = _c(DIM, "○ idle")

        print(f"\n  {_c(BOLD, 'RSS PIPELINE')}  ciclo {_c(BOLD, str(rss_cycle))}  {rss_status_str}  {_c(DIM, f'{rss_elapsed:.0f}s')}")

        # Stage 1
        s1_pct = f"{rss_done/rss_total*100:.0f}%" if rss_total else "—"
        print(
            f"    {'Stage 1 (fetch)':<20}  "
            f"{_c(BOLD, str(rss_done))}/{_c(DIM, str(rss_total))}  {_c(DIM, s1_pct)}  "
            + (_c(RED, f"  erros={err_total}") if err_total else "")
        )

        # Stage 2
        w_col = GREEN if s2_workers > 0 else DIM
        q12_col = YELLOW if s1s2_depth > 20 else (CYAN if s1s2_depth > 0 else DIM)
        print(
            f"    {'Stage 2 (process)':<20}  "
            f"{_c(BOLD, str(rss_proc))}/{_c(DIM, str(rss_queued))}  "
            f"workers={_c(w_col+BOLD, str(s2_workers))}  "
            f"fila S1→S2={_c(q12_col+BOLD, str(s1s2_depth))}"
        )

        # Stage 3
        q23_col = YELLOW if s2s3_depth > 10 else (CYAN if s2s3_depth > 0 else DIM)
        print(
            f"    {'Stage 3 (DB write)':<20}  "
            f"artigos novos={_c(GREEN+BOLD, str(rss_art))}  "
            f"fila S2→S3={_c(q23_col+BOLD, str(s2s3_depth))}"
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
    # Watermark: anchor at the START of each drain phase.
    # wm_pending/wm_ts are fixed throughout a drain phase; they only reset when
    # pending INCREASES (burst of new articles), starting a new phase.
    # This lets the elapsed time grow so drain rate is stable and meaningful.
    wm_pending: int | None = None
    wm_ts:      float | None = None
    prev_pend:  int | None = None
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
            if "_error" not in data:
                if first_sample is None:
                    first_sample = s
                cur_pend = _get(data, "articles", "enrich_pending")
                if wm_pending is None:
                    # First sample — initialise anchor
                    wm_pending = cur_pend
                    wm_ts      = ts
                elif prev_pend is not None and cur_pend > prev_pend:
                    # Pending went up (burst of new articles) — reset phase anchor
                    wm_pending = cur_pend
                    wm_ts      = ts
                # else: pending equal or decreasing → keep anchor fixed
                prev_pend = cur_pend
            print_snapshot(samples, first_sample, wm_pending, wm_ts, interval_s, seq)

            elapsed = time.monotonic() - t0
            sleep_s = max(0.0, interval_s - elapsed)
            time.sleep(sleep_s)

    except KeyboardInterrupt:
        print(_c(DIM, "\n\nMonitor encerrado."))
        sys.exit(0)


if __name__ == "__main__":
    main()
