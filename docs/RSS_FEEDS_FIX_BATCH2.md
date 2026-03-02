# RSS Feeds - Correção Batch 2
**Data:** 2026-03-01 16:49

## Feeds Deletados (RSS desativado pelos sites)

### 1. Korea Times (2 feeds)
- **rss-korea-times**: `https://www.koreatimes.co.kr/www/rss/news.xml` → HTTP 404
- **rss-www-koreatimes-co-kr**: `https://www.koreatimes.co.kr/www/rss/rss.xml` → HTTP 200 mas sem entradas
- **Alternativa testada**: `https://feed.koreatimes.co.kr/k/allnews.xml` → HTTP 200 mas sem entradas
- **Conclusão**: Korea Times desativou completamente os feeds RSS

### 2. Scientific American
- **rss-scientific-american**: `https://www.scientificamerican.com/feed/` → HTTP 404
- **Alternativas testadas**: 
  - `/feeds/news/` → HTTP 404
  - `rss.sciam.com/ScientificAmerican-Global` → Conexão falha
- **Conclusão**: Scientific American desativou RSS

### 3. Haaretz English
- **rss-haaretz-english**: `https://www.haaretz.com/cmlink/1.628152` → Retorna HTML em vez de RSS
- **Nota**: Outros feeds Haaretz funcionam:
  - `rss-www-haaretz-com` → 100 entradas ✅
  - `rss-haaretz-com` (Security) → 35 entradas ✅

## Feeds Atualizados

### 1. New Zealand Herald
- **ID**: rss-new-zealand-herald
- **Nome**: New Zealand Herald → **New Zealand Herald Business**
- **URL antiga**: `https://www.nzherald.co.nz/arc/outboundfeeds/rss/curated/78/`
  - Erro: Connection aborted, HTTPException (got more than 100 headers)
- **URL nova**: `https://www.nzherald.co.nz/arc/outboundfeeds/rss/section/business/?outputType=xml`
  - Status: HTTP 200 ✅
  - Entradas: 10 artigos
  - Content-Type: application/xml

## Resultado
- **Deletados**: 4 feeds
- **Atualizados**: 1 feed
- **Total RSS**: 550 fontes ativas (de 1001 total)
- **Status**: Serviço reiniciado com sucesso (PID 2837396)
- **Verificação**: Nenhum erro nos logs após restart

## Comandos Executados
```sql
DELETE FROM gm_sources WHERE id_source = 'rss-korea-times';
DELETE FROM gm_sources WHERE id_source = 'rss-www-koreatimes-co-kr';
DELETE FROM gm_sources WHERE id_source = 'rss-scientific-american';
DELETE FROM gm_sources WHERE id_source = 'rss-haaretz-english';

UPDATE gm_sources 
SET url = 'https://www.nzherald.co.nz/arc/outboundfeeds/rss/section/business/?outputType=xml',
    name = 'New Zealand Herald Business'
WHERE id_source = 'rss-new-zealand-herald';
```
