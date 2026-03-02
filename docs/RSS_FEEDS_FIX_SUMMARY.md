# RSS Feeds - Análise e Correções Necessárias
**Data:** 1 de março de 2026

## ✅ Feeds Que Podem Ser Corrigidos

### 1. BBC News (CORRIGIR)
- **Problema:** DNS error - `feeds.bbcnews.com` não resolve mais
- **URL Antiga:** `http://feeds.bbcnews.com/news/rss.xml`
- **URL Nova:** `https://feeds.bbci.co.uk/news/rss.xml`
- **Status:** ✅ Testado - 37 entries funcionando
- **Ação:** UPDATE na table gm_sources

```sql
UPDATE gm_sources 
SET url = 'https://feeds.bbci.co.uk/news/rss.xml'
WHERE id_source = 'rss-bbc-news';
```

---

## ❌ Feeds Sem RSS Disponível (BLOQUEAR)

### 2. Reuters
- **Problema:** HTTP 401 - Now requires authentication
- **URL:** `https://www.reutersagency.com/feed/`
- **Tentativas:** Testado múltiplas URLs alternativas - todas retornam 401 ou 404
- **Ação:** BLOQUEAR fonte `rss-reuters`
- **Nota:** Reuters desativou feeds RSS públicos

### 3. Associated Press  
- **Problema:** DNS error - `feeds.apnews.com` não existe mais
- **URL:** `https://feeds.apnews.com/rss/apf-topnews`
- **Tentativas:** apnews.com/rss retorna 404, rsshub retorna 403
- **Ação:** BLOQUEAR fonte `rss-associated-press`
- **Nota:** AP desativou domínio de feeds

### 4. The Sun
- **Problema:** Invalid content type - Retorna HTML ao invés de RSS
- **URL:** `https://www.thesun.co.uk/news/worldnews/feed/`
- **Tentativas:** Múltiplas URLs testadas - todas retornam HTML (anti-bot)
- **Ação:**  BLOQUEAR fonte `rss-www-thesun-co-uk`
- **Nota:** Site bloqueia crawlers de RSS

### 5. USA Today
- **Problema:** Invalid content type - Retorna HTML ao invés de RSS
- **URL:** `http://rssfeeds.usatoday.com/usatoday-NewsTopStories`
- **Tentativas:** Testado /rss/ e /rss/news/ - 404 ou 406
- **Ação:** BLOQUEAR fonte `rss-usa-today`
- **Nota:** Desativaram feeds RSS públicos

### 6. Bloomberg
- **Problema:** HTTP 403 - Blocked
- **URL:** `https://www.bloomberg.com/feed/news.rss`
- **Tentativas:** Múltiplas URLs - todas retornam 403
- **Ação:** BLOQUEAR fonte `rss-bloomberg`
- **Nota:** Bloomberg bloqueia acesso a feeds RSS

---

## ⚠️ Outros Erros (Artigos, não feeds)

### CNN Collections (404)
- **URLs:** `/collections/intl-trump-040223/`, `/collections/intl-ukraine-030423/`
- **Problema:** URLs antigas from 2023 que não existem mais
-  **Origem:** Provavelmente artigos vindos do NewsAPI, não são feeds RSS
- **Ação:** Nenhuma - são artigos antigos que geraram 404 ao tentar fetch

### ABC News Live (404)
- **URL:** `https://abcnews.com/Live/video/abcnews-live-41463246`
- **Problema:** URL antiga de vídeo live que não existe mais
- **Origem:** Artigo do NewsAPI
- **Ação:** Nenhuma - artigo antigo

### news18.com (Redirect Loop)
- **Problema:** Exceeded 30 redirects
- **Origem:** Artigo individual com URL malformada (encoding issues)
- **Ação:** Nenhuma - erro isolado de artigo

---

## 💾 SQL para Aplicar Correções

```sql
-- 1. Corrigir BBC News
UPDATE gm_sources 
SET url = 'https://feeds.bbci.co.uk/news/rss.xml'
WHERE id_source = 'rss-bbc-news';

-- 2. Bloquear feeds sem RSS disponível
UPDATE gm_sources
SET fetch_blocked = 1,
    blocked_count = 999
WHERE id_source IN (
    'rss-reuters',
    'rss-associated-press',
    'rss-www-thesun-co-uk',
    'rss-usa-today',
    'rss-bloomberg'
);

-- 3. Verificar alterações
SELECT id_source, name, fetch_blocked, url
FROM gm_sources
WHERE id_source IN (
    'rss-bbc-news',
    'rss-reuters',
    'rss-associated-press',
    'rss-www-thesun-co-uk',
    'rss-usa-today',
    'rss-bloomberg'
)
ORDER BY fetch_blocked, id_source;
```

---

## 📊 Resumo

| Feed | Status Atual | Ação | Motivo |
|------|-------------|------|--------|
| BBC News | DNS Error | ✅ CORRIGIR | Mudou domínio para feeds.bbci.co.uk |
| Reuters | 401 Unauthorized | ❌ BLOQUEAR | Requer autenticação |
| Associated Press | DNS Error | ❌ BLOQUEAR | Domínio desativado |
| The Sun | Invalid HTML | ❌ BLOQUEAR | Bloqueia crawlers |
| USA Today | 404/406 | ❌ BLOQUEAR | Feeds RSS desativados |
| Bloomberg | 403 Forbidden | ❌ BLOQUEAR | Bloqueia acesso |

**Total: 1 correção, 5 bloqueios**

---

## 📝 Notas

- A maioria dos grandes publishers desativou ou bloqueou feeds RSS públicos
- BBC News é o único dos testados que ainda mantém RSS público funcional
- Feeds NewsAPI desses outlets continuam funcionando (Reuters, AP, etc.)
- Erros de 404 em artigos individuais são normais (links expirados/movidos)
