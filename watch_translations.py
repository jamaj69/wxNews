#!/usr/bin/env python3
"""
Monitoramento contínuo do progresso de tradução.
Atualiza a cada N segundos. Ctrl+C para sair.

Usa a API REST do serviço (/api/monitor) em vez de acesso directo ao banco —
todos os dados passam pelo NewsDatabase centralizado.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from decouple import config as env_config

API_BASE = str(env_config('MONITOR_API_URL', default='http://localhost:8765'))
INTERVAL = int(env_config('TRANSLATE_CYCLE_INTERVAL', default=2))


# ─── HTTP helper ─────────────────────────────────────────────────────

def _fetch(path: str, timeout: float = 5.0) -> dict[str, Any]:
    url = f"{API_BASE.rstrip('/')}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError) as err:
        return {"_error": str(err), "success": False}


# ─── State ─────────────────────────────────────────────────────

@dataclass
class MonitorState:
    prev_translated: int | None = None
    rates: list[int] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)


# ─── Display helpers ───────────────────────────────────────────────────

def _bar(done: int, total: int, width: int = 30) -> str:
    if total == 0:
        return "[" + "-" * width + "]"
    filled = int(width * done / total)
    return "[" + "█" * filled + "─" * (width - filled) + "]"


def _clear() -> None:
    sys.stdout.write("\033[H\033[J")
    sys.stdout.flush()


# ─── Render ──────────────────────────────────────────────────────

def render(data: dict[str, Any], state: MonitorState) -> None:
    if "_error" in data:
        _clear()
        print(f"\033[31m  Erro ao contactar API: {data['_error']}\033[0m")
        print(f"  URL: {API_BASE}/api/monitor")
        print(f"  A retentar em {INTERVAL}s…")
        return

    total         = data.get("total", 0)
    enriched      = data.get("enriched", 0)
    not_enriched  = data.get("not_enriched", 0)
    enrich_failed = data.get("enrich_failed", 0)
    translated    = data.get("translated", 0)
    trans_pending = data.get("translate_pending", 0)
    top: list[dict] = data.get("pending_by_language", [])

    pct_enrich = (enriched / total * 100) if total else 0
    total_pipeline = trans_pending + translated
    pct_trans = (translated / total_pipeline * 100) if total_pipeline else 0
    now = time.time()

    # Calcular taxa de tradução
    if state.prev_translated is not None:
        delta = translated - state.prev_translated
        state.rates.append(delta)
        if len(state.rates) > 30:
            state.rates.pop(0)
        rate_per_s = sum(state.rates) / (len(state.rates) * INTERVAL)
        rate_per_h = rate_per_s * 3600
        if rate_per_s > 0 and trans_pending > 0:
            eta_s = trans_pending / rate_per_s
            h, rem = divmod(int(eta_s), 3600)
            m, s = divmod(rem, 60)
            eta_str = f"{h}h {m:02d}m {s:02d}s"
        else:
            eta_str = "calculando..."
    else:
        rate_per_h = 0.0
        eta_str = "calculando..."

    state.prev_translated = translated

    _clear()
    print("━" * 60)
    print("  📊  MONITOR DE ARTIGOS & TRADUÇÕES")
    print("━" * 60)
    print(f"  {'ARTIGOS':38}")
    print(f"  Total       : {total:>10,}")
    print(f"  Enriquecidos: \033[32m{enriched:>10,}\033[0m  {_bar(enriched, total)}  {pct_enrich:.1f}%")
    print(f"  Não enriq.  : \033[33m{not_enriched:>10,}\033[0m")
    print(f"  Falha enriq.: \033[31m{enrich_failed:>10,}\033[0m")
    print("━" * 60)

    # ── Tiers de enriquecimento ──────────────────────────────────────
    tiers: list[dict] = data.get("enrichment_tiers", [])
    if tiers:
        print(f"  {'TIERS DE ENRIQUECIMENTO':38}")
        print(f"  {'Backend':<12} {'Pendente':>9} {'Em Voo':>7} {'Resolvido':>9} {'Avançado':>9} {'Descartado':>10}")
        print("  " + "─" * 56)
        _TIER_COLORS = {'cffi': '\033[36m', 'requests': '\033[35m', 'playwright': '\033[33m'}
        for tier in tiers:
            backend  = tier.get("backend",  "?")
            col      = _TIER_COLORS.get(backend, '')
            pending  = tier.get("pending",  0)
            in_fl    = tier.get("in_flight", 0)
            resolved = tier.get("resolved", 0)
            advanced = tier.get("advanced", 0)
            gave_up  = tier.get("gave_up",  0)
            print(
                f"  {col}\033[1m{backend:<12}\033[0m"
                f" \033[33m{pending:>9,}\033[0m"
                f" \033[36m{in_fl:>7,}\033[0m"
                f" \033[32m{resolved:>9,}\033[0m"
                f" \033[2m{advanced:>9,}\033[0m"
                f" \033[31m{gave_up:>10,}\033[0m"
            )
        print("━" * 60)

    print(f"  {'PIPELINE':38}")
    print(f"  Pend. enriq.: \033[33m{not_enriched:>10,}\033[0m")
    print(f"  Pend. trad. : \033[33m{trans_pending:>10,}\033[0m")
    print(f"  Traduzidos  : \033[32m{translated:>10,}\033[0m")
    print(f"  Total (pipe): {total_pipeline:>10,}")
    print(f"  Trad. prog. : {_bar(translated, total_pipeline)}  {pct_trans:.1f}%")
    print("━" * 60)
    if top:
        print(f"  Pendentes por idioma (tradução):")
        print(f"  {'lang':<6} {'nome':<18} → {'destino':<6} {'qtd':>7}")
        print("  " + "─" * 44)
        for row in top:
            lang   = str(row.get("detected_language") or "?")
            name   = str(row.get("language_name")     or "?")
            target = str(row.get("target_language")   or "?")
            n      = int(row.get("n", 0))
            print(f"  {lang:<6} {name:<18} → {target:<6} {n:>7,}")
        print("━" * 60)
    print(f"  Ritmo trad. :   ~{rate_per_h:,.0f} artigos/hora")
    print(f"  ETA trad.   :   {eta_str}")
    print("━" * 60)
    elapsed = int(now - state.start_time)
    h2, rem2 = divmod(elapsed, 3600)
    m2, s2 = divmod(rem2, 60)
    print(f"  Monitorando há {h2}h {m2:02d}m {s2:02d}s  •  Ctrl+C para sair")
    print("━" * 60)


# ─── Main loop ─────────────────────────────────────────────────────

def main() -> None:
    state = MonitorState()
    print("\033[?25l", end="")  # ocultar cursor
    try:
        while True:
            t0   = time.monotonic()
            data = _fetch("/api/monitor")
            render(data, state)
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, INTERVAL - elapsed))
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h", end="")  # restaurar cursor
        _clear()
        print("Monitor encerrado.")


if __name__ == "__main__":
    main()


def query():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        # ── Totais gerais ──────────────────────────────────────────────────
        cur.execute("SELECT COUNT(*) FROM gm_articles")
        total_articles = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM gm_articles WHERE is_enriched = 1")
        enriched = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM gm_articles WHERE is_enriched = 0")
        not_enriched = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM gm_articles WHERE is_enriched = -1")
        enrich_failed = cur.fetchone()[0]
        # ── Estado pipeline ────────────────────────────────────────────────
        cur.execute("SELECT COUNT(*) FROM v_articles_pending_enrichment")
        pending_enrich = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM v_articles_pending_translation")
        pending_trans = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM gm_articles WHERE is_translated = 1")
        translated = cur.fetchone()[0]
        # ── Top idiomas pendentes tradução ─────────────────────────────────
        cur.execute("""
            SELECT detected_language, language_name, target_language, COUNT(*) AS n
            FROM v_articles_pending_translation
            GROUP BY detected_language
            ORDER BY n DESC
            LIMIT 10
        """)
        top = cur.fetchall()
    finally:
        con.close()
    return total_articles, enriched, not_enriched, enrich_failed, \
           pending_enrich, pending_trans, translated, top

def clear_screen():
    # Move cursor to top-left and clear screen
    sys.stdout.write("\033[H\033[J")
    sys.stdout.flush()

def bar(done, total, width=30):
    if total == 0:
        return "[" + "-" * width + "]"
    filled = int(width * done / total)
    return "[" + "█" * filled + "─" * (width - filled) + "]"

def main():
    prev_translated = None
    start_time = time.time()
    rates = []

    print("\033[?25l", end="")  # ocultar cursor
    try:
        while True:
            total_articles, enriched, not_enriched, enrich_failed, \
                pending_enrich, pending_trans, translated, top = query()

            pct_enrich = (enriched / total_articles * 100) if total_articles else 0
            total_pipeline = pending_enrich + pending_trans + translated
            pct_trans = (translated / total_pipeline * 100) if total_pipeline else 0
            now = time.time()

            # Calcular taxa de tradução
            if prev_translated is not None:
                delta = translated - prev_translated
                rates.append(delta)
                if len(rates) > 30:  # média dos últimos 30 snapshots (60s)
                    rates.pop(0)
                rate_per_s = sum(rates) / (len(rates) * INTERVAL)
                rate_per_h = rate_per_s * 3600
                eta_s = (pending_trans / rate_per_s) if rate_per_s > 0 else None
                if eta_s and eta_s > 0:
                    h, rem = divmod(int(eta_s), 3600)
                    m, s = divmod(rem, 60)
                    eta_str = f"{h}h {m:02d}m {s:02d}s"
                else:
                    eta_str = "calculando..."
            else:
                rate_per_h = 0
                eta_str = "calculando..."

            prev_translated = translated

            clear_screen()
            print("━" * 52)
            print("  📊  MONITOR DE ARTIGOS & TRADUÇÕES")
            print("━" * 52)
            print(f"  {'ARTIGOS':38}")
            print(f"  Total       : {total_articles:>10,}")
            print(f"  Enriquecidos: \033[32m{enriched:>10,}\033[0m  {bar(enriched, total_articles)}  {pct_enrich:.1f}%")
            print(f"  Não enriq.  : \033[33m{not_enriched:>10,}\033[0m")
            print(f"  Falha enriq.: \033[31m{enrich_failed:>10,}\033[0m")
            print("━" * 52)
            print(f"  {'PIPELINE':38}")
            print(f"  Pend. enriq.: \033[33m{pending_enrich:>10,}\033[0m")
            print(f"  Pend. trad. : \033[33m{pending_trans:>10,}\033[0m")
            print(f"  Traduzidos  : \033[32m{translated:>10,}\033[0m")
            print(f"  Total (pipe): {total_pipeline:>10,}")
            print(f"  Trad. prog. : {bar(translated, total_pipeline)}  {pct_trans:.1f}%")
            print("━" * 52)
            if top:
                print(f"  Pendentes por idioma (tradução):")
                print(f"  {'lang':<6} {'nome':<18} → {'destino':<6} {'qtd':>7}")
                print("  " + "─" * 44)
                for lang, name, target, n in top:
                    print(f"  {str(lang):<6} {str(name):<18} → {str(target):<6} {n:>7,}")
                print("━" * 52)
            print(f"  Ritmo trad. :   ~{rate_per_h:,.0f} artigos/hora")
            print(f"  ETA trad.   :   {eta_str}")
            print("━" * 52)
            elapsed = int(now - start_time)
            h, rem = divmod(elapsed, 3600)
            m, s2 = divmod(rem, 60)
            print(f"  Monitorando há {h}h {m:02d}m {s2:02d}s  •  Ctrl+C para sair")
            print("━" * 52)

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h", end="")  # restaurar cursor
        clear_screen()
        print("Monitor encerrado.")

if __name__ == "__main__":
    main()
