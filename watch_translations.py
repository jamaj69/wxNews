#!/usr/bin/env python3
"""
Monitoramento contínuo do progresso de tradução.
Atualiza a cada 2 segundos. Ctrl+C para sair.
"""
import sqlite3
import time
import sys
import os
from decouple import config as env_config

DB_PATH = os.path.join(os.path.dirname(__file__), "predator_news.db")
# Mesmo parâmetro usado pelo serviço de tradução
INTERVAL = int(env_config('TRANSLATE_CYCLE_INTERVAL', default=2))

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
