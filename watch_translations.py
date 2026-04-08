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
        cur.execute("SELECT COUNT(*) FROM gm_articles WHERE is_translated=1")
        translated = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM v_articles_pending_translation")
        pending = cur.fetchone()[0]
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
    return translated, pending, top

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
            translated, pending, top = query()
            total = translated + pending
            pct = (translated / total * 100) if total else 0
            now = time.time()

            # Calcular taxa
            if prev_translated is not None:
                delta = translated - prev_translated
                rates.append(delta)
                if len(rates) > 30:  # média dos últimos 30 snapshots (60s)
                    rates.pop(0)
                rate_per_s = sum(rates) / (len(rates) * INTERVAL)
                rate_per_h = rate_per_s * 3600
                eta_s = (pending / rate_per_s) if rate_per_s > 0 else None
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
            print("  📊  MONITOR DE TRADUÇÕES")
            print("━" * 52)
            print(f"  Pendentes por idioma:")
            print(f"  {'lang':<6} {'nome':<18} → {'destino':<6} {'qtd':>7}")
            print("  " + "─" * 44)
            for lang, name, target, n in top:
                print(f"  {str(lang):<6} {str(name):<18} → {str(target):<6} {n:>7,}")
            print("━" * 52)
            print(f"  Traduzidos : \033[32m{translated:>8,}\033[0m")
            print(f"  Pendentes  : \033[33m{pending:>8,}\033[0m")
            print(f"  Total      :   {total:>8,}")
            print(f"  Progresso  :   {bar(translated, total)}  {pct:.1f}%")
            print(f"  Ritmo      :   ~{rate_per_h:,.0f} artigos/hora")
            print(f"  ETA        :   {eta_str}")
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
