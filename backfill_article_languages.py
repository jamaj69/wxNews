#!/usr/bin/env python3
"""
Script para detectar e atualizar idiomas de artigos existentes em lote.
Processa todos os artigos que não têm detected_language definido.
"""
import sqlite3
import time
import signal
import sys
from typing import Optional, Tuple

# Importar função de detecção de idioma
try:
    from langdetect import detect, LangDetectException
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    print("⚠️  AVISO: langdetect não instalado. Instale com: pip install langdetect")
    sys.exit(1)

# Configurações
DB_PATH = '/home/jamaj/src/python/pyTweeter/predator_news.db'
BATCH_SIZE = 1000  # Processar 1000 artigos por lote
COMMIT_INTERVAL = 100  # Commit a cada 100 artigos processados

# Controle de interrupção
stop_processing = False

def signal_handler(signum, frame):
    """Handler para Ctrl+C - permite parada segura"""
    global stop_processing
    print("\n\n⚠️  Interrupção solicitada. Finalizando lote atual...")
    stop_processing = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def detect_article_language(title: str, description: str, content: str) -> Tuple[Optional[str], float]:
    """
    Detecta o idioma de um artigo usando langdetect.
    
    Args:
        title: Título do artigo
        description: Descrição/sumário do artigo  
        content: Conteúdo completo do artigo
        
    Returns:
        (language_code, confidence) ou (None, 0.0) se não conseguir detectar
    """
    if not LANGDETECT_AVAILABLE:
        return None, 0.0
    
    # Concatenar texto disponível para análise
    text_parts = []
    if title:
        text_parts.append(title)
    if description:
        text_parts.append(description)
    if content:
        text_parts.append(content[:500])  # Limitar conteúdo para performance
    
    text = " ".join(text_parts).strip()
    
    # Precisa de pelo menos 20 caracteres para detecção confiável
    if len(text) < 20:
        return None, 0.0
    
    try:
        language = detect(text)
        # langdetect não retorna confidence diretamente, assumir 0.85 como padrão
        confidence = 0.85
        return language, confidence
    except LangDetectException:
        return None, 0.0
    except Exception as e:
        print(f"⚠️  Erro na detecção: {e}")
        return None, 0.0


def process_batch(conn: sqlite3.Connection, offset: int) -> int:
    """
    Processa um lote de artigos sem idioma detectado.
    
    Returns:
        Número de artigos processados com sucesso
    """
    cursor = conn.cursor()
    
    # Buscar lote de artigos
    cursor.execute("""
        SELECT id_article, title, description, content
        FROM gm_articles
        WHERE detected_language IS NULL
        LIMIT ? OFFSET ?
    """, (BATCH_SIZE, offset))
    
    articles = cursor.fetchall()
    
    if not articles:
        return 0
    
    processed = 0
    detected = 0
    
    for article in articles:
        if stop_processing:
            break
            
        id_article, title, description, content = article
        
        # Detectar idioma
        language, confidence = detect_article_language(title, description, content)
        
        if language:
            # Atualizar artigo
            cursor.execute("""
                UPDATE gm_articles
                SET detected_language = ?,
                    language_confidence = ?
                WHERE id_article = ?
            """, (language, confidence, id_article))
            detected += 1
        
        processed += 1
        
        # Commit a cada COMMIT_INTERVAL artigos
        if processed % COMMIT_INTERVAL == 0:
            conn.commit()
            print(f"    ✓ {processed}/{len(articles)} processados, {detected} detectados")
    
    # Commit final do lote
    conn.commit()
    
    return processed


def main():
    print("=" * 70)
    print("📚 PROCESSAMENTO EM LOTE: Detecção de Idioma de Artigos")
    print("=" * 70)
    print()
    
    # Conectar ao banco
    print(f"Conectando ao banco: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Contar artigos sem idioma
    cursor.execute("SELECT COUNT(*) FROM gm_articles WHERE detected_language IS NULL")
    total_without_language = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM gm_articles")
    total_articles = cursor.fetchone()[0]
    
    print(f"Total de artigos: {total_articles:,}")
    print(f"Sem idioma detectado: {total_without_language:,}")
    print(f"Com idioma detectado: {total_articles - total_without_language:,}")
    print()
    
    if total_without_language == 0:
        print("✅ Todos os artigos já têm idioma detectado!")
        conn.close()
        return
    
    print(f"⚙️  Configuração:")
    print(f"   - Tamanho do lote: {BATCH_SIZE}")
    print(f"   - Commits a cada: {COMMIT_INTERVAL} artigos")
    print(f"   - Tempo estimado: ~{total_without_language // 100 // 60} minutos")
    print()
    print("💡 Pressione Ctrl+C para interromper com segurança")
    print()
    print("-" * 70)
    
    # Processar em lotes
    start_time = time.time()
    total_processed = 0
    total_detected = 0
    offset = 0
    batch_num = 0
    
    while offset < total_without_language and not stop_processing:
        batch_num += 1
        print(f"\n📦 Lote #{batch_num} (artigos {offset+1} a {min(offset+BATCH_SIZE, total_without_language)})")
        
        batch_start = time.time()
        processed = process_batch(conn, offset)
        batch_time = time.time() - batch_start
        
        if processed == 0:
            break
        
        total_processed += processed
        
        # Contar quantos foram detectados neste lote
        cursor.execute("""
            SELECT COUNT(*) 
            FROM gm_articles 
            WHERE detected_language IS NOT NULL
        """)
        current_detected = cursor.fetchone()[0]
        batch_detected = current_detected - total_detected
        total_detected = current_detected
        
        # Estatísticas do lote
        articles_per_sec = processed / batch_time if batch_time > 0 else 0
        progress_pct = (total_processed / total_without_language) * 100
        
        print(f"   ⏱️  Tempo: {batch_time:.1f}s ({articles_per_sec:.0f} artigos/s)")
        print(f"   ✅ Detectados: {batch_detected}/{processed} ({batch_detected/processed*100:.1f}%)")
        print(f"   📊 Progresso: {total_processed:,}/{total_without_language:,} ({progress_pct:.1f}%)")
        
        offset += BATCH_SIZE
        
        # Pequena pausa entre lotes
        if not stop_processing and offset < total_without_language:
            time.sleep(0.1)
    
    # Estatísticas finais
    elapsed_time = time.time() - start_time
    
    print()
    print("=" * 70)
    print("📊 RESUMO FINAL")
    print("=" * 70)
    
    cursor.execute("SELECT COUNT(*) FROM gm_articles WHERE detected_language IS NOT NULL")
    final_detected = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM gm_articles WHERE detected_language IS NULL")
    final_without = cursor.fetchone()[0]
    
    print(f"Artigos processados: {total_processed:,}")
    print(f"Tempo total: {elapsed_time/60:.1f} minutos ({elapsed_time:.0f}s)")
    print(f"Velocidade média: {total_processed/elapsed_time:.0f} artigos/segundo")
    print()
    print(f"✅ Com idioma: {final_detected:,} ({final_detected/total_articles*100:.1f}%)")
    print(f"❌ Sem idioma: {final_without:,} ({final_without/total_articles*100:.1f}%)")
    print()
    
    # Mostrar idiomas detectados
    cursor.execute("""
        SELECT detected_language, COUNT(*) as total
        FROM gm_articles
        WHERE detected_language IS NOT NULL
        GROUP BY detected_language
        ORDER BY total DESC
        LIMIT 10
    """)
    
    print("🌍 Top 10 idiomas detectados:")
    for lang, count in cursor.fetchall():
        pct = (count / final_detected) * 100
        print(f"   {lang}: {count:,} ({pct:.1f}%)")
    
    print()
    print("=" * 70)
    
    if stop_processing:
        print("⚠️  Processamento interrompido pelo usuário")
    else:
        print("✅ Processamento concluído com sucesso!")
    
    conn.close()


if __name__ == "__main__":
    main()
