#!/usr/bin/env python3
"""
Quick GMT Coverage Checker - Usa views do banco de dados
Verificação rápida de fontes com artigos sem GMT
"""

import sqlite3
import sys

DB_PATH = 'predator_news.db'

def print_header(title):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def check_sources_missing_gmt():
    """Lista fontes com artigos sem GMT"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print_header("TOP 20 FONTES COM ARTIGOS SEM GMT")
    
    cursor.execute("""
        SELECT 
            source_name,
            source_timezone,
            total_articles,
            articles_without_gmt,
            ROUND(gmt_coverage_pct, 1) || '%' AS coverage
        FROM v_source_gmt_coverage
        WHERE articles_without_gmt > 0
        ORDER BY articles_without_gmt DESC
        LIMIT 20
    """)
    
    print(f"\n{'Fonte':<35} {'Timezone':<12} {'Total':>7} {'Missing':>8} {'Coverage':>10}")
    print("-" * 80)
    
    for row in cursor.fetchall():
        source_name, tz, total, missing, coverage = row
        tz_display = tz if tz else "---"
        print(f"{source_name:<35} {tz_display:<12} {total:>7} {missing:>8} {coverage:>10}")
    
    conn.close()

def show_statistics():
    """Mostra estatísticas gerais"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print_header("ESTATÍSTICAS GERAIS DE COBERTURA GMT")
    
    cursor.execute("SELECT * FROM v_gmt_statistics")
    stats = cursor.fetchone()
    
    if stats:
        total_sources, sources_100pct, sources_missing, total_articles, \
        total_with_gmt, total_without_gmt, overall_coverage = stats
        
        print(f"\n📊 Fontes:")
        print(f"   Total de fontes:             {total_sources:>6}")
        print(f"   Fontes com 100% cobertura:   {sources_100pct:>6} ({sources_100pct/total_sources*100:.1f}%)")
        print(f"   Fontes com artigos faltando: {sources_missing:>6} ({sources_missing/total_sources*100:.1f}%)")
        
        print(f"\n📰 Artigos:")
        print(f"   Total de artigos:            {total_articles:>6,}")
        print(f"   COM GMT:                     {total_with_gmt:>6,} ({overall_coverage:.2f}%)")
        print(f"   SEM GMT:                     {total_without_gmt:>6,} ({100-overall_coverage:.2f}%)")
    
    conn.close()

def check_source_details(source_name_pattern):
    """Detalha uma fonte específica"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print_header(f"DETALHES DA FONTE: {source_name_pattern}")
    
    cursor.execute("""
        SELECT 
            source_name,
            source_timezone,
            category,
            language,
            total_articles,
            articles_with_gmt,
            articles_without_gmt,
            gmt_coverage_pct
        FROM v_source_gmt_coverage
        WHERE source_name LIKE ?
    """, (f"%{source_name_pattern}%",))
    
    results = cursor.fetchall()
    
    if not results:
        print(f"\n❌ Nenhuma fonte encontrada com o padrão '{source_name_pattern}'")
        conn.close()
        return
    
    for row in results:
        source_name, tz, cat, lang, total, with_gmt, without_gmt, coverage = row
        
        print(f"\n📌 {source_name}")
        print(f"   Timezone:          {tz if tz else 'Não configurado'}")
        print(f"   Categoria:         {cat if cat else '---'}")
        print(f"   Idioma:            {lang if lang else '---'}")
        print(f"   Total de artigos:  {total:,}")
        print(f"   Com GMT:           {with_gmt:,} ({coverage:.1f}%)")
        print(f"   Sem GMT:           {without_gmt:,} ({100-coverage:.1f}%)")
        
        # Mostrar alguns exemplos de artigos sem GMT
        cursor.execute("""
            SELECT title, publishedAt
            FROM v_articles_missing_gmt
            WHERE source_name = ?
            LIMIT 3
        """, (source_name,))
        
        examples = cursor.fetchall()
        if examples:
            print(f"\n   📄 Exemplos de artigos sem GMT:")
            for i, (title, pub_date) in enumerate(examples, 1):
                title_short = title[:60] + "..." if len(title) > 60 else title
                print(f"      {i}. {pub_date} - {title_short}")
    
    conn.close()

def list_views():
    """Lista views disponíveis"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print_header("VIEWS DISPONÍVEIS")
    
    cursor.execute("""
        SELECT name, sql 
        FROM sqlite_master 
        WHERE type='view' AND name LIKE 'v_%'
        ORDER BY name
    """)
    
    for name, sql in cursor.fetchall():
        print(f"\n📊 {name}")
        # Pegar primeira linha do comentário se existir
        if sql and '--' in sql:
            lines = sql.split('\n')
            for line in lines:
                if line.strip().startswith('--'):
                    print(f"   {line.strip()}")
                    break
    
    conn.close()

def main():
    """Main function"""
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'list' or command == 'sources':
            check_sources_missing_gmt()
        elif command == 'stats':
            show_statistics()
        elif command == 'views':
            list_views()
        elif command == 'source' and len(sys.argv) > 2:
            source_pattern = ' '.join(sys.argv[2:])
            check_source_details(source_pattern)
        else:
            print("Uso:")
            print("  python3 check_gmt_coverage.py list     - Lista fontes com artigos sem GMT")
            print("  python3 check_gmt_coverage.py stats    - Mostra estatísticas gerais")
            print("  python3 check_gmt_coverage.py views    - Lista views disponíveis")
            print("  python3 check_gmt_coverage.py source <nome> - Detalhes de uma fonte")
            print("\nExemplos:")
            print("  python3 check_gmt_coverage.py list")
            print("  python3 check_gmt_coverage.py stats")
            print("  python3 check_gmt_coverage.py source Guardian")
            print("  python3 check_gmt_coverage.py source 'Notícias ao Minuto'")
    else:
        # Default: mostra tudo
        show_statistics()
        check_sources_missing_gmt()

if __name__ == '__main__':
    main()
