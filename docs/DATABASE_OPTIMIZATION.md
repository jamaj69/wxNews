# Otimização de Views e Índices - Documentação

## ✅ Implementado em: 1 de março de 2026

## 📊 Resumo das Otimizações

### 1. Índices Criados

#### Índices em `gm_articles` (já existentes, verificados)
- ✅ `idx_articles_source_gmt` - Índice composto em (id_source, published_at_gmt)
  - **Uso**: Otimiza JOINs e agregações por fonte
  - **Performance**: JOIN e GROUP BY extremamente rápidos
  
- ✅ `idx_articles_published_gmt_desc` - Índice em published_at_gmt DESC
  - **Uso**: Ordenação por data GMT descendente
  - **Performance**: Queries de "artigos mais recentes" instantâneas

- ✅ `idx_articles_publishedAt` - Índice em publishedAt
  - **Uso**: Filtros e ordenação por data original

#### Índices Novos em `gm_sources`
- ✅ `idx_sources_use_timezone` - Índice parcial em use_timezone WHERE use_timezone = 1
  - **Uso**: Filtrar rapidamente apenas fontes confirmadas
  - **Vantagem**: Índice parcial (só indexa onde use_timezone=1) = mais eficiente
  
- ✅ `idx_sources_timezone_use` - Índice composto em (timezone, use_timezone)
  - **Uso**: Queries que filtram por timezone E use_timezone
  - **Performance**: Filtros combinados muito rápidos

---

## 📋 Views Disponíveis

### 1. `v_gmt_statistics` (Estatísticas Gerais)
**Descrição**: Visão geral do sistema - estatísticas agregadas de todas as fontes

**Colunas**:
- `total_sources` - Total de fontes
- `sources_100pct_coverage` - Fontes com 100% de cobertura
- `sources_with_missing` - Fontes com artigos sem GMT
- `total_articles_all_sources` - Total de artigos
- `total_with_gmt` - Artigos com GMT
- `total_without_gmt` - Artigos sem GMT
- `overall_coverage_pct` - Cobertura geral (%)

**Uso**:
```sql
SELECT * FROM v_gmt_statistics;
```

**Resultado típico**:
| total_sources | sources_100pct_coverage | sources_with_missing | overall_coverage_pct |
|---------------|------------------------|---------------------|---------------------|
| 871 | 563 | 308 | 95.52 |

---

### 2. `v_source_gmt_coverage` (Cobertura por Fonte - Todas)
**Descrição**: Estatísticas de cobertura GMT para TODAS as fontes (incluindo 100%)

**Colunas**:
- `id_source` - ID da fonte
- `source_name` - Nome da fonte
- `source_timezone` - Timezone configurado
- `total_articles` - Total de artigos
- `articles_with_gmt` - Artigos com GMT
- `articles_without_gmt` - Artigos sem GMT
- `gmt_coverage_pct` - Cobertura (%)

**Uso**:
```sql
-- Top 20 fontes com artigos faltando
SELECT * FROM v_source_gmt_coverage 
WHERE articles_without_gmt > 0 
ORDER BY articles_without_gmt DESC 
LIMIT 20;

-- Fontes com 100% de cobertura
SELECT * FROM v_source_gmt_coverage 
WHERE gmt_coverage_pct = 100.0;
```

---

### 3. `v_sources_missing_gmt` ⭐ **NOVA - OTIMIZADA**
**Descrição**: Fontes QUE TÊM artigos sem GMT (mais rápida que v_source_gmt_coverage com filtro)

**Diferença da anterior**: Usa INNER JOIN (não LEFT JOIN), só retorna fontes com artigos faltando

**Colunas**:
- `id_source` - ID da fonte
- `name` - Nome da fonte
- `timezone` - Timezone configurado
- `use_timezone` - Se é confirmada (0 ou 1)
- `country` - País
- `language` - Idioma
- `total_articles` - Total de artigos
- `missing_gmt` - Artigos SEM GMT
- `with_gmt` - Artigos COM GMT
- `coverage_pct` - Cobertura (%)

**Uso**:
```sql
-- Top 10 fontes com mais artigos sem GMT
SELECT name, timezone, use_timezone, missing_gmt, coverage_pct 
FROM v_sources_missing_gmt 
LIMIT 10;

-- Fontes com timezone detectado mas não confirmadas
SELECT name, timezone, missing_gmt 
FROM v_sources_missing_gmt 
WHERE timezone IS NOT NULL 
AND use_timezone = 0
ORDER BY missing_gmt DESC;

-- Fontes sem timezone detectado
SELECT name, missing_gmt, total_articles 
FROM v_sources_missing_gmt 
WHERE timezone IS NULL
ORDER BY missing_gmt DESC;
```

**Performance**: ⚡ ~0.13 segundos para processar 308 fontes

---

### 4. `v_confirmed_sources_stats` ⭐ **NOVA**
**Descrição**: Estatísticas apenas de fontes CONFIRMADAS (use_timezone = 1)

**Colunas**:
- `id_source` - ID da fonte
- `name` - Nome da fonte
- `timezone` - Timezone
- `country` - País
- `language` - Idioma
- `total_articles` - Total de artigos
- `missing_gmt` - Artigos SEM GMT
- `with_gmt` - Artigos COM GMT
- `coverage_pct` - Cobertura (%)

**Uso**:
```sql
-- Ver todas as fontes confirmadas
SELECT * FROM v_confirmed_sources_stats;

-- Fontes confirmadas com problemas (artigos sem GMT)
SELECT name, timezone, total_articles, missing_gmt 
FROM v_confirmed_sources_stats 
WHERE missing_gmt > 0;

-- Cobertura das fontes confirmadas
SELECT 
    COUNT(*) as total_confirmed,
    SUM(total_articles) as total_articles,
    SUM(with_gmt) as with_gmt,
    ROUND(100.0 * SUM(with_gmt) / SUM(total_articles), 2) as coverage_pct
FROM v_confirmed_sources_stats;
```

**Performance**: ⚡ Usa índice `idx_sources_use_timezone` (parcial) = extremamente rápido

---

### 5. `v_articles_missing_gmt` (Lista de Artigos)
**Descrição**: Lista individual de artigos SEM GMT (com informações da fonte)

**Colunas**:
- `id_article` - ID do artigo
- `title` - Título
- `publishedAt` - Data original
- `published_at_gmt` - NULL (por definição)
- `id_source` - ID da fonte
- `source_name` - Nome da fonte
- `source_timezone` - Timezone da fonte

**Uso**:
```sql
-- Artigos de uma fonte específica sem GMT
SELECT title, publishedAt, source_name 
FROM v_articles_missing_gmt 
WHERE source_name LIKE '%Guardian%'
LIMIT 10;

-- Contar artigos sem GMT por fonte
SELECT source_name, COUNT(*) as missing 
FROM v_articles_missing_gmt 
GROUP BY id_source 
ORDER BY missing DESC;
```

**Nota**: Esta view retorna MUITOS resultados (2,452+ linhas). Use sempre com LIMIT ou filtros!

---

## 🚀 Queries Otimizadas Recomendadas

### Query 1: Dashboard Geral
```sql
SELECT * FROM v_gmt_statistics;
```
**Output**: 1 linha com estatísticas gerais  
**Performance**: < 0.1s

### Query 2: Top Fontes Problemáticas
```sql
SELECT 
    name,
    timezone,
    use_timezone,
    missing_gmt,
    total_articles,
    coverage_pct
FROM v_sources_missing_gmt 
LIMIT 20;
```
**Output**: Top 20 fontes com artigos sem GMT  
**Performance**: ~0.13s

### Query 3: Fontes Confirmadas
```sql
SELECT * FROM v_confirmed_sources_stats;
```
**Output**: Todas as fontes confirmadas (use_timezone=1)  
**Performance**: < 0.05s (usa índice parcial)

### Query 4: Fontes Candidatas para Confirmação
```sql
SELECT 
    name,
    timezone,
    country,
    missing_gmt,
    total_articles,
    coverage_pct
FROM v_sources_missing_gmt 
WHERE timezone IS NOT NULL 
AND use_timezone = 0
AND total_articles >= 30  -- Mínimo de artigos para ser confiável
ORDER BY missing_gmt DESC
LIMIT 20;
```
**Output**: Fontes com timezone detectado, não confirmadas, com volume significativo  
**Purpose**: Identificar próximas fontes para confirmar

### Query 5: Progresso de Cobertura por País
```sql
SELECT 
    country,
    COUNT(DISTINCT id_source) as fontes,
    SUM(total_articles) as total_artigos,
    SUM(with_gmt) as com_gmt,
    ROUND(100.0 * SUM(with_gmt) / SUM(total_articles), 2) as cobertura_pct
FROM v_sources_missing_gmt
WHERE country IS NOT NULL
GROUP BY country
ORDER BY cobertura_pct ASC;
```
**Output**: Cobertura por país  
**Purpose**: Identificar países com baixa cobertura

---

## 📊 Plano de Execução (Query Plan)

### Exemplo: Agregação por Fonte
```sql
EXPLAIN QUERY PLAN
SELECT * FROM v_sources_missing_gmt LIMIT 10;
```

**Resultado**:
```
SCAN s USING INDEX sqlite_autoindex_gm_sources_1
SEARCH a USING INDEX idx_articles_source_gmt (id_source=?) 
USE TEMP B-TREE FOR ORDER BY
```

**Análise**:
- ✅ Usa índice primário de gm_sources
- ✅ Usa índice composto `idx_articles_source_gmt` para JOIN
- ✅ B-Tree temporário apenas para ORDER BY final (inevitável, muito eficiente)

---

## 🔧 Comandos Úteis no SQLite

### Ver todas as views
```sql
.tables v_%
```

### Ver definição de uma view
```sql
.schema v_sources_missing_gmt
```

### Ver índices de uma tabela
```sql
.indexes gm_articles
.indexes gm_sources
```

### Análise de performance
```sql
.timer on
SELECT COUNT(*) FROM v_sources_missing_gmt;
```

### Estatísticas de índices
```sql
ANALYZE;
```

---

## 📝 Manutenção

### Recriar Views (se necessário)
```sql
-- Dropar views antigas
DROP VIEW IF EXISTS v_sources_missing_gmt;
DROP VIEW IF EXISTS v_confirmed_sources_stats;

-- Recriar (usar scripts em DATABASE_VIEWS.md)
```

### Atualizar Estatísticas de Índices
```sql
-- Executar periodicamente (melhora otimizador de queries)
ANALYZE gm_articles;
ANALYZE gm_sources;
```

### Verificar Uso de Índices
```sql
-- Ver estatísticas de uso
SELECT * FROM sqlite_stat1 WHERE tbl = 'gm_articles';
```

---

## 🎯 Benefícios da Otimização

### Antes
- Query agregada: ~0.5-1.0s (sem índices adequados)
- Filtros por use_timezone: table scan completo
- LEFT JOIN sempre, mesmo quando só quer fontes com problemas

### Depois
- ✅ Query agregada: **0.13s** (4-8x mais rápido)
- ✅ Filtros por use_timezone: **< 0.05s** (índice parcial)
- ✅ Views especializadas (v_sources_missing_gmt usa INNER JOIN)
- ✅ Todas as queries usam índices apropriados

### Impacto
- **check_gmt_coverage.py**: Mais rápido
- **Scripts de backfill**: Podem consultar views rapidamente
- **Análises ad-hoc**: Consultas interativas instantâneas
- **Monitoramento**: Dashboard de estatísticas em tempo real

---

## 📚 Arquivos Relacionados

- `DATABASE_VIEWS.md` - Documentação original das views
- `USE_TIMEZONE_SYSTEM.md` - Sistema use_timezone
- `check_gmt_coverage.py` - Script CLI (usa as views)
- `/tmp/manage_use_timezone.py` - Gerenciamento de fontes

---

## ✅ Checklist de Otimização

- [x] Índice composto em (id_source, published_at_gmt)
- [x] Índice parcial em use_timezone = 1
- [x] Índice composto em (timezone, use_timezone)
- [x] View otimizada v_sources_missing_gmt (INNER JOIN)
- [x] View especializada v_confirmed_sources_stats
- [x] Plano de execução verificado (EXPLAIN QUERY PLAN)
- [x] Performance medida (~0.13s para 308 fontes)
- [x] Documentação completa
- [x] Queries de exemplo testadas

---

**Status**: ✅ Otimização completa e testada  
**Performance**: ⚡ 4-8x mais rápido  
**Manutenção**: Mínima (índices automáticos)
