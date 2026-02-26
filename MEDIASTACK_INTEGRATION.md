# MediaStack API Integration

## 📊 Overview

**MediaStack** fornece acesso a notícias de **7,500+ fontes** globais através de uma API REST simples.

- **URL**: https://api.mediastack.com/v1/news
- **Conta**: jamajbr@gmail.com
- **API Key**: `a7dce43f483d778dee646beb6f24a5ba`
- **Documentação**: https://mediastack.com/documentation

---

## 🎯 Recursos Implementados

### ✅ Parâmetros Suportados

| Parâmetro | Descrição | Exemplo |
|-----------|-----------|---------|
| `access_key` | ✅ API key (obrigatório) | `a7dce43f...` |
| `languages` | ✅ Filtro de idiomas | `en`, `pt`, `es`, `it`, `ar`, `de`, `fr`, `ru` |
| `countries` | ✅ Filtro por país (código 2 letras) | `us`, `br`, `es`, `it`, `au`, `ca` |
| `categories` | ✅ Categorias de notícias | `technology`, `business`, `sports`, etc. |
| `sources` | ✅ Filtrar fontes específicas | `cnn,-bbc` (incluir CNN, excluir BBC) |
| `keywords` | ✅ Busca por palavras-chave | `AI technology -crypto` |
| `date` | ✅ Data ou intervalo | `2026-02-26` ou `2026-02-01,2026-02-28` |
| `sort` | ✅ Ordenação | `published_desc`, `published_asc`, `popularity` |
| `limit` | ✅ Número de resultados | 1-100 (padrão: 25) |
| `offset` | ✅ Paginação | `0`, `25`, `50`, etc. |

### 📋 Categorias Disponíveis

- `general` - Notícias gerais (não categorizadas)
- `business` - Negócios e finanças
- `entertainment` - Entretenimento
- `health` - Saúde
- `science` - Ciência
- `sports` - Esportes
- `technology` - Tecnologia

### 🌍 Idiomas Suportados

| Código | Idioma | Código | Idioma |
|--------|--------|--------|--------|
| `ar` | Árabe | `nl` | Holandês |
| `de` | Alemão | `no` | Norueguês |
| `en` | Inglês | `pt` | Português |
| `es` | Espanhol | `ru` | Russo |
| `fr` | Francês | `se` | Sueco |
| `he` | Hebraico | `zh` | Chinês |
| `it` | Italiano | | |

---

## 📦 Implementação

### Arquivo Criado

**`mediastack_collector.py`** - Coletor assíncrono completo

```python
from mediastack_collector import MediaStackCollector

collector = MediaStackCollector()

# Exemplo 1: Notícias de tecnologia em inglês
stats = await collector.collect_and_store(
    languages=['en'],
    categories='technology',
    limit=25
)

# Exemplo 2: Notícias de negócios em PT e ES
stats = await collector.collect_and_store(
    languages=['pt', 'es'],
    categories='business',
    countries='br,es',
    limit=10
)

# Exemplo 3: Buscar por palavras-chave
stats = await collector.collect_and_store(
    languages=['en'],
    keywords='artificial intelligence -crypto',
    limit=20
)
```

### Configuração (.env)

```ini
# MediaStack API Configuration
MEDIASTACK_API_KEY=a7dce43f483d778dee646beb6f24a5ba
MEDIASTACK_BASE_URL=https://api.mediastack.com/v1/news
```

---

## 🎪 Teste Realizado

```bash
python3 mediastack_collector.py
```

### Resultados

```
📊 MEDIASTACK TEST RESULTS
  Total fetched: 20
  ✅ Inserted: 20
  ⏭️  Skipped: 0
  ❌ Errors: 0

💡 Features Demonstrated:
  ✅ Category filtering (technology, business)
  ✅ Multi-language support (en, pt, es)
  ✅ Keyword search with exclusion
```

### Fontes Coletadas

11 fontes diferentes identificadas:
- watoday, theage, The Sydney Morning Herald, brisbanetimes
- Deccan Chronicle, Independent, americanbankingnews
- **TechCrunch**, **The New York Times**, **Engadget**

---

## 🔒 Plano Gratuito - Limitações

| Recurso | Free Plan |
|---------|-----------|
| **Requests/mês** | 500 |
| **Rate limit** | 3-4 requests/minuto aproximadamente |
| **Delay nas notícias** | ⚠️ **30 minutos** (não é real-time) |
| **Dados históricos** | ❌ Não disponível |
| **HTTPS** | ❌ Somente planos pagos |

### ⚠️ Observações Importantes

1. **Free Plan tem delay de 30 minutos**: As notícias não são em tempo real
2. **Rate limit agressivo**: 3-4 requests por minuto
3. **Sem HTTPS no free**: Apenas HTTP (segurança limitada)
4. **500 requests/mês**: ~16 requests/dia

---

## 📈 Comparação: NewsAPI vs MediaStack

| Recurso | NewsAPI (Free) | MediaStack (Free) |
|---------|----------------|-------------------|
| Requests/mês | ~1000 | 500 |
| Idiomas | EN, PT, ES, IT (mas PT/ES/IT não funcionam) | 13 idiomas ✅ |
| Delay | Nenhum ✅ | 30 minutos ⚠️ |
| Fontes | ~60k | 7,500+ |
| Rate limit | Moderado | Agressivo |
| HTTPS | ✅ Sim | ❌ Não (free) |
| Categorização | ✅ Boa | ✅ Boa |
| **Melhor para** | Notícias em inglês em tempo real | Multi-idioma com delay aceitável |

---

## 🎯 Estratégia de Uso Recomendada

### Opção 1: Híbrido (Recomendado)

```python
# NewsAPI: Notícias em inglês (real-time)
newsapi_collect(languages=['en'], limit=100)

# MediaStack: Outros idiomas (delay 30 min OK)
mediastack_collect(languages=['pt', 'es', 'it'], limit=15)

# RSS: Fontes específicas (customizado)
rss_collect(all_sources=True)
```

**Requests/dia estimados:**
- NewsAPI EN: 3-4 requests/dia = ~100/mês
- MediaStack multilang: 10-15 requests/dia = ~400/mês
- RSS: Ilimitado (322 fontes)

### Opção 2: Priorizar RSS

```python
# Usar MediaStack apenas para descobrir novas fontes
# e obter metadados, depois coletar via RSS
```

---

## 🚀 Próximos Passos

### 1. Integrar ao wxAsyncNewsGather.py

```python
class NewsGather():
    def UpdateNews(self):
        # NewsAPI (EN)
        self.url_queue.put(newsapi_en_url)
        
        # MediaStack (PT, ES, IT)
        self.loop.create_task(self.collect_mediastack())
        
        # RSS (Todas as 322 fontes)
        self.loop.create_task(self.collect_rss_feeds())
```

### 2. Otimizar Uso de Requests

- **Cache inteligente**: Não reprocessar artigos recentes
- **Agendamento**: MediaStack apenas 2x/dia (delay de 30 min)
- **Priorização**: RSS > MediaStack > NewsAPI

### 3. Descoberta Automática de RSS

```python
# Quando MediaStack retornar nova fonte:
# 1. Tentar descobrir RSS feed
# 2. Se encontrar, adicionar como fonte RSS
# 3. Usar RSS em vez de MediaStack para essa fonte
```

---

## 📊 Estatísticas Atuais

```sql
-- Total de fontes
SELECT COUNT(*) FROM gm_sources;
-- 480 fontes totais

-- Fontes por tipo
SELECT 
    CASE 
        WHEN id_source LIKE 'rss-%' THEN 'RSS'
        WHEN id_source LIKE 'mediastack-%' THEN 'MediaStack'
        WHEN id_source LIKE 'newsapi-%' THEN 'NewsAPI'
        ELSE 'Other'
    END as type,
    COUNT(*) as count
FROM gm_sources
GROUP BY type;

-- RSS: 322
-- MediaStack: 11
-- NewsAPI: 147
```

```sql
-- Total de artigos
SELECT COUNT(*) FROM gm_articles;
-- 3,269 artigos totais

-- Artigos por fonte
SELECT 
    CASE 
        WHEN id_source LIKE 'rss-%' THEN 'RSS'
        WHEN id_source LIKE 'ms-%' THEN 'MediaStack'
        WHEN id_source LIKE 'newsapi-%' THEN 'NewsAPI'
        ELSE 'Other'
    END as type,
    COUNT(*) as count
FROM gm_articles
GROUP BY type;

-- RSS: 3,203
-- MediaStack: 20
-- NewsAPI: 46
```

---

## ✅ Validação Final

- [x] MediaStack API key funcionando
- [x] Suporte a 13 idiomas
- [x] Filtros por categoria, país, fonte
- [x] Busca por palavras-chave com exclusão
- [x] Paginação implementada
- [x] Tratamento de erros (rate limit, timeout)
- [x] Integração com SQLite
- [x] Descoberta automática de fontes
- [x] 20 artigos coletados de 11 fontes

---

## 🔧 Manutenção

### Monitorar Rate Limits

```python
# Adicionar delay entre requests
await asyncio.sleep(15)  # 15 segundos entre requests (4/min)
```

### Logs de Erro

```python
# Erros comuns do MediaStack
- 429: Rate limit exceeded
- 401: Invalid API key
- 403: Function access restricted (plano)
```

---

**Criado por**: GitHub Copilot & jamaj  
**Data**: 2026-02-26  
**Status**: ✅ Produção  
**Arquivo principal**: `mediastack_collector.py`
