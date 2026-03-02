# Views de Análise GMT - Banco de Dados

Este documento descreve as views criadas para facilitar a análise de cobertura GMT no banco de dados.

## Views Disponíveis

### 1. `v_source_gmt_coverage`
**Propósito:** Análise de cobertura GMT por fonte

**Colunas:**
- `id_source`: ID único da fonte
- `source_name`: Nome da fonte
- `source_timezone`: Timezone configurado
- `category`: Categoria da fonte
- `language`: Idioma
- `total_articles`: Total de artigos da fonte
- `articles_with_gmt`: Artigos com `published_at_gmt` preenchido
- `articles_without_gmt`: Artigos sem `published_at_gmt`
- `gmt_coverage_pct`: Percentual de cobertura (0-100)

**Ordenação:** Por `articles_without_gmt` DESC (fontes com mais problemas primeiro)

---

### 2. `v_articles_missing_gmt`
**Propósito:** Listagem de artigos individuais sem GMT

**Colunas:**
- `id_article`: ID do artigo
- `id_source`: ID da fonte
- `source_name`: Nome da fonte
- `source_timezone`: Timezone da fonte
- `title`: Título do artigo
- `publishedAt`: Timestamp original
- `published_at_gmt`: Campo GMT (NULL)
- `url`: URL do artigo

**Ordenação:** Por `publishedAt` DESC (mais recentes primeiro)

---

### 3. `v_gmt_statistics`
**Propósito:** Estatísticas gerais agregadas

**Colunas:**
- `total_sources`: Total de fontes no banco
- `sources_100pct_coverage`: Fontes com 100% de cobertura
- `sources_with_missing`: Fontes com artigos sem GMT
- `total_articles_all_sources`: Total de artigos (todas as fontes)
- `total_with_gmt`: Total de artigos com GMT
- `total_without_gmt`: Total de artigos sem GMT
- `overall_coverage_pct`: Cobertura geral em percentual

---

## Queries Úteis

### 1. Top 10 fontes com mais artigos sem GMT
```sql
SELECT 
    source_name,
    source_timezone,
    total_articles,
    articles_without_gmt,
    gmt_coverage_pct || '%' AS coverage
FROM v_source_gmt_coverage
WHERE articles_without_gmt > 0
ORDER BY articles_without_gmt DESC
LIMIT 10;
```

### 2. Fontes com 100% de cobertura
```sql
SELECT 
    source_name,
    source_timezone,
    total_articles
FROM v_source_gmt_coverage
WHERE articles_without_gmt = 0
ORDER BY total_articles DESC
LIMIT 20;
```

### 3. Fontes por idioma com problemas
```sql
SELECT 
    language,
    COUNT(*) AS sources_count,
    SUM(articles_without_gmt) AS total_missing
FROM v_source_gmt_coverage
WHERE articles_without_gmt > 0
GROUP BY language
ORDER BY total_missing DESC;
```

### 4. Fontes com timezone mas com artigos sem GMT
```sql
SELECT 
    source_name,
    source_timezone,
    articles_without_gmt,
    gmt_coverage_pct || '%' AS coverage
FROM v_source_gmt_coverage
WHERE source_timezone IS NOT NULL
  AND articles_without_gmt > 0
ORDER BY articles_without_gmt DESC;
```

### 5. Estatísticas gerais
```sql
SELECT * FROM v_gmt_statistics;
```

### 6. Artigos recentes sem GMT (últimos 100)
```sql
SELECT 
    source_name,
    title,
    publishedAt,
    source_timezone
FROM v_articles_missing_gmt
LIMIT 100;
```

### 7. Contagem de artigos sem GMT por fonte (resumo rápido)
```sql
SELECT 
    source_name,
    articles_without_gmt
FROM v_source_gmt_coverage
WHERE articles_without_gmt > 0
ORDER BY articles_without_gmt DESC;
```

### 8. Fontes candidatas para correção (com timezone e >= 50 artigos problemáticos)
```sql
SELECT 
    id_source,
    source_name,
    source_timezone,
    articles_without_gmt,
    gmt_coverage_pct || '%' AS coverage
FROM v_source_gmt_coverage
WHERE source_timezone IS NOT NULL
  AND articles_without_gmt >= 50
ORDER BY articles_without_gmt DESC;
```

---

## Como Usar no Terminal

### SQLite CLI (formato tabela)
```bash
sqlite3 predator_news.db -header -column "SELECT * FROM v_source_gmt_coverage LIMIT 10;"
```

### SQLite CLI (formato CSV)
```bash
sqlite3 predator_news.db -csv "SELECT * FROM v_source_gmt_coverage WHERE articles_without_gmt > 0;" > missing_gmt.csv
```

### Python
```python
import sqlite3

conn = sqlite3.connect('predator_news.db')
cursor = conn.cursor()

# Query usando a view
cursor.execute("SELECT * FROM v_source_gmt_coverage WHERE articles_without_gmt > 0")
for row in cursor.fetchall():
    print(row)

# Estatísticas gerais
cursor.execute("SELECT * FROM v_gmt_statistics")
stats = cursor.fetchone()
print(f"Cobertura geral: {stats[-1]}%")

conn.close()
```

---

## Manutenção das Views

### Recriar view
```sql
DROP VIEW IF EXISTS v_source_gmt_coverage;
CREATE VIEW v_source_gmt_coverage AS ...
```

### Listar todas as views
```sql
SELECT name FROM sqlite_master WHERE type='view' ORDER BY name;
```

### Remover uma view
```sql
DROP VIEW IF EXISTS v_source_gmt_coverage;
```

---

## Performance

As views são **queries virtuais** - não armazenam dados, apenas definem a consulta.
- ✅ Sempre retornam dados atualizados
- ✅ Economia de tempo de desenvolvimento
- ⚠️ Performance depende dos índices nas tabelas base

### Índices recomendados para performance
```sql
CREATE INDEX IF NOT EXISTS idx_articles_source_gmt ON gm_articles(id_source, published_at_gmt);
CREATE INDEX IF NOT EXISTS idx_articles_publishedAt ON gm_articles(publishedAt);
```

---

## Estado Atual (2 de março de 2026)

Estatísticas após correções (Phase 1, 2 e 3):
- **Total de fontes:** 868
- **Fontes com 100% cobertura:** 554 (63.8%)
- **Fontes com artigos faltando:** 314 (36.2%)
- **Cobertura geral:** 89.38% (48,709 / 54,496 artigos)
- **Artigos restantes sem GMT:** 5,787 (10.62%)

Principais fontes problemáticas:
1. Notícias ao Minuto (3 edições): ~2,089 artigos - feed sem timezone
2. All News: 447 artigos - feed sem timezone
3. zazoom: 405 artigos - feed sem timezone
4. Exame: 315 artigos - feed sem timezone
5. Nature News: 91 artigos - feed apenas com data (sem hora/timezone)
