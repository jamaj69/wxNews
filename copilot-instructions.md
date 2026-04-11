# wxNews - Instruções do Sistema

Sistema de agregação e leitura de notícias com coleta automática via RSS/NewsAPI/MediaStack e interface gráfica moderna com FastAPI backend.

---

## 🚀 Gerenciamento do Serviço wxAsyncNewsGatherAPI

> ⚠️ **IMPORTANTE**: O serviço systemd executa **`wxAsyncNewsGather.py`** (não `wxAsyncNewsGatherAPI.py`).
> O arquivo `wxAsyncNewsGatherAPI.py` é legado e **não é mais usado**.
> O arquivo principal é `wxAsyncNewsGather.py`, que contém FastAPI + coletores + backfill + tradução.

O serviço está configurado como **systemd service** e roda tanto o coletor quanto a API REST.

### Iniciar o Serviço
```bash
sudo systemctl start wxAsyncNewsGather.service
```

### Verificar Status do Serviço
```bash
sudo systemctl status wxAsyncNewsGather.service
```

### Parar o Serviço
```bash
sudo systemctl stop wxAsyncNewsGather.service
```

### Reiniciar o Serviço
```bash
sudo systemctl restart wxAsyncNewsGather.service
```

### Ver Logs em Tempo Real
```bash
journalctl -u wxAsyncNewsGather.service -f
```

### Ver Últimas Linhas do Log (últimas 50)
```bash
journalctl -u wxAsyncNewsGather.service -n 50
```

### Ver Logs com Erro
```bash
journalctl -u wxAsyncNewsGather.service -p err
```

### Habilitar Serviço no Boot
```bash
sudo systemctl enable wxAsyncNewsGather.service
```

### Desabilitar Serviço no Boot
```bash
sudo systemctl disable wxAsyncNewsGather.service
```

### Recarregar Configuração do Systemd (após editar .service)
```bash
sudo systemctl daemon-reload
sudo systemctl restart wxAsyncNewsGather.service
```

### Ver Arquivo de Unidade do Serviço
```bash
cat /etc/systemd/system/wxAsyncNewsGather.service
```

### Execução Manual (para debug)
```bash
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate
python wxAsyncNewsGather.py
```

### Acessar Documentação da API
```bash
# Swagger UI (interativo)
firefox http://localhost:8765/docs

# ReDoc (alternativo)
firefox http://localhost:8765/redoc

# Health check
curl http://localhost:8765/api/health
```

---

## 🔍 Debug e Diagnóstico

### Verificar Coleta de Notícias
```bash
# Ver últimas notícias coletadas
sqlite3 predator_news.db "SELECT datetime(published_at_gmt, 'unixepoch') as data, 
    title, source_name FROM gm_articles ORDER BY published_at_gmt DESC LIMIT 10;"

# Contar artigos por fonte (últimas 24h)
sqlite3 predator_news.db "SELECT source_name, COUNT(*) as total 
    FROM gm_articles 
    WHERE published_at_gmt > unixepoch('now', '-1 day')
    GROUP BY source_name 
    ORDER BY total DESC LIMIT 20;"

# Total de artigos no banco
sqlite3 predator_news.db "SELECT COUNT(*) as total FROM gm_articles;"
```

### Verificar Cobertura GMT (Timezone)
```bash
# Script de verificação
python check_gmt_coverage.py

# Ver estatísticas de timezone
sqlite3 predator_news.db "
SELECT 
    source_name,
    use_timezone,
    timezone,
    COUNT(*) as total_articles
FROM gm_articles 
WHERE published_at_gmt IS NOT NULL 
GROUP BY source_name 
ORDER BY total_articles DESC 
LIMIT 30;"
```

### Monitorar Fontes com Problemas
```bash
# Fontes na blocklist
python check_blocklist.py

# Diagnosticar feeds com problemas
python diagnose_feeds.py

# Verificar URLs RSS quebradas
cat broken_rss_urls.txt
```

### Debug dos Fetchers IPC (article_fetcher + workers)
```bash
# Testar o orquestrador completo (smoke test)
python article_fetcher.py https://www.reuters.com/world/

# Testar worker cffi isolado
python - <<'EOF'
import multiprocessing, cffi_worker
ctx = multiprocessing.get_context('spawn')
req_q, resp_q = ctx.Queue(), ctx.Queue()
p = ctx.Process(target=cffi_worker.worker, args=(req_q, resp_q)); p.start()
req_q.put(('t1', 'https://www.reuters.com/world/', 10))
print(resp_q.get(timeout=15))
req_q.put(None); p.join()
EOF

# Ver logs dos workers em tempo real
journalctl -u wxAsyncNewsGather.service -f | grep -E 'cffi|requests|playwright|fetcher|TIMEOUT|blocked'

# Verificar fontes bloqueadas por erros permanentes
sqlite3 predator_news.db "SELECT source_name, blocked_count FROM gm_sources WHERE fetch_blocked=1;"

# Desbloquear todas as fontes (após diagnosticar)
sqlite3 predator_news.db "UPDATE gm_sources SET fetch_blocked=0, blocked_count=0;"
```

> Ver **[ARCHITECTURE.md](ARCHITECTURE.md) § 9** para playbook completo de debug dos fetchers.

### Ver Logs em Tempo Real
```bash
# Via systemd journal
journalctl -u wxAsyncNewsGather.service -f

# Ver últimas 100 linhas
journalctl -u wxAsyncNewsGather.service -n 100

# Ver apenas erros
journalctl -u wxAsyncNewsGather.service -p err -f

# Ver logs de hoje
journalctl -u wxAsyncNewsGather.service --since today

# Ver logs de tradução
journalctl -u wxAsyncNewsGather.service -f | grep -E '🌐|Translation|Translat'
```

---

## 📂 Estrutura do Sistema

### Diretórios Principais

```
pyTweeter/
├── docs/                          # 📚 Documentação (30+ arquivos .md)
│   ├── README.md
│   ├── USE_TIMEZONE_SYSTEM.md
│   ├── TIMEZONE_BACKFILL_COMPLETE.md
│   └── [outros guides e reports]
│
├── scripts/timezone/              # 🔧 Scripts de backfill/teste (gitignored)
│   ├── backfill_*.py             # Scripts de backfill de timezone
│   ├── validate_*.py             # Scripts de validação
│   └── *.sh                      # Shell scripts de monitoramento
│
├── wxAsyncNewsGather.py          # 🚀 ARQUIVO PRINCIPAL (FastAPI + Coletor + Backfill + Tradução)
├── wxAsyncNewsGatherAPI.py       # ⚠️  LEGADO — não usado pelo serviço systemd
├── wxAsyncNewsReaderv6.py        # 📱 Interface gráfica moderna
│
├── article_fetcher.py            # 📄 Orquestrador IPC de busca de conteúdo
├── cffi_worker.py                # 🔀 Subprocess — curl_cffi Chrome TLS
├── requests_worker.py            # 🔀 Subprocess — requests com headers de browser
├── playwright_worker.py          # 🔀 Subprocess — Chromium headless (Playwright)
│
├── translatev1.py                # 🌐 Orquestrador IPC de tradução
├── google_worker.py              # 🔀 Subprocess — Google Translate
├── nllb_worker.py                # 🔀 Subprocess — modelo NLLB offline
│
├── async_tickdb.py               # ⏰ Sistema de agendamento
│
├── predator_news.db              # 💾 Banco de dados SQLite (~55k artigos)
├── .env                          # 🔐 Credenciais (NEWS_API_KEY_1, etc)
├── requirements-fastapi.txt      # 📦 Dependências FastAPI
├── requirements.txt              # 📦 Todas as dependências
└── .gitignore                    # 🚫 Exclusões do git
```

### Arquivos Principais

#### 🚀 wxAsyncNewsGather.py (Arquivo Principal — executado pelo systemd)
- **Função**: Aplicação principal unificada: FastAPI + coletores + backfill + tradução
- **Recursos**:
  - FastAPI server na porta 8765
  - Coleta paralela: NewsAPI, RSS feeds, MediaStack
  - Backfill de conteúdo de artigos (`backfill_content`) — pipeline em 3 tiers
  - Tradução automática de artigos (`backfill_translations`)
  - Sistema de timezone automático (96.5% cobertura GMT)
  - Blocklist para fontes problemáticas
  - Deduplicação por URL
  - Cache de stats de fila (atualizado a cada 20s por `_refresh_queue_stats`)
  - REST API com endpoints:
    - GET /api/health - Health check
    - GET /api/articles - Query articles com timestamp
    - GET /api/sources - Lista de fontes
    - GET /api/stats - Estatísticas de coleta (total, last_24h, last_hour, total_sources)
    - GET /api/queues - Stats detalhadas de enriquecimento + tradução + tiers
    - GET /api/monitor - Stats completas para dashboards externos
    - GET /api/latest_timestamp - Último timestamp
    - GET /docs - Swagger UI interativo
- **Arquivo de serviço**: `/etc/systemd/system/wxAsyncNewsGather.service`
- **Config**: Usa variáveis do `.env` (API_KEY1, API_KEY2, DB_PATH, etc)

#### ⚠️  wxAsyncNewsGatherAPI.py (LEGADO — não usar)
- **Função**: Versão antiga/incompleta do serviço
- **NÃO é executado pelo systemd** — o serviço aponta para `wxAsyncNewsGather.py`
- Não possui tasks de backfill nem tradução
- Mantido apenas por compatibilidade histórica

#### 📱 wxAsyncNewsReaderv6.py (Interface)
- **Função**: Interface gráfica para leitura de notícias
- **Recursos**:
  - wx.Notebook com abas
  - wx.CheckListBox com 480+ fontes
  - Seleção múltipla de fontes
  - Botões: Select All / Deselect All / Load Checked
  - Ordenação por published_at_gmt DESC
  - Visualização HTML com wx.html2
  - Auto-reload ao mudar checkbox
  - **Polling da API FastAPI** (NewsAPIClient):
    - Intervalo: 30 segundos (configurável)
    - Endpoint: http://localhost:8765/api/articles
    - Usando timestamp-based queries para eficiência
  - Filtragem de timestamps futuros (data integrity)
- **Execução**:
  ```bash
  cd /home/jamaj/src/python/pyTweeter
  source /home/python/pyenv/bin/activate
  python wxAsyncNewsReaderv6.py
  ```
- **Configuração** (.env):
  ```bash
  NEWS_API_URL=http://localhost:8765
  NEWS_POLL_INTERVAL_MS=30000  # 30 segundos
  ```

#### 💾 predator_news.db (Banco de Dados)
- **Engine**: SQLite com WAL mode (permite leituras concorrentes com escritas)
- **Tamanho actual**: ~2 GB (682k+ artigos, Abr 2026)
- **Tabelas principais**:
  - `gm_articles`: Artigos coletados
  - `gm_sources`: Fontes de notícias (1639+)
  - `gm_newsapi_sources`: Fontes do NewsAPI
  - `gm_blocked_domains`: Domínios bloqueados por erros repetidos
  - `languages`: Tabela de suporte a idiomas com flag `translate`
- **Campos importantes em gm_articles**:
  - `title`, `url`, `description`, `author`
  - `published_at`: Timestamp original
  - `published_at_gmt`: Timestamp convertido para GMT (Unix epoch)
  - `source_name`, `id_source`
  - `content`: Conteúdo completo do artigo (quando disponível)
  - `use_timezone`: Flag indicando se usa sistema de timezone
  - `is_enriched`: 0=pendente, 1=enriquecido, -1=falhou
  - `enrich_try`: Tier que deve processar (0=cffi, 1=requests, 2=playwright)
  - `is_translated`: 0=pendente, 1=traduzido, -1=ignorado
  - `detected_language`: Idioma detectado pelo serviço de linguagem
- **Índices relevantes**:
  - `idx_articles_enriched_translated` — (is_enriched, is_translated)
  - `idx_articles_enrich_try` — (is_enriched, enrich_try)
  - `idx_stats_translate_pending` — parcial WHERE is_translated=0
  - `idx_articles_inserted_ms` — inserted_at_ms DESC

#### ⚙️ article_fetcher.py (Orquestrador IPC de conteúdo)
- **Função**: Orquestrador de busca de conteúdo de artigos via IPC
- **Arquitetura**: base `_ProcessFetcher` + 3 subclasses que spawnam subprocessos
- **Workers**:
  - `cffi_worker.py` — `curl_cffi` com fingerprint Chrome TLS (JA3/JA4), bypass Cloudflare
  - `requests_worker.py` — `requests` com headers de browser (fallback se cffi indisponível)
  - `playwright_worker.py` — Chromium headless via Playwright (fallback final: JS, bot-block)
- **Protocolo IPC**: `(req_id, url, timeout)` → `(req_id, {html, success, error_code, error_type})`
- **Lógica de orquestração**: cffi → requests → playwright (somente se 403/406, erro temporário, ou HTML sem conteúdo)
- **API pública**: `fetch_article_content(url, timeout=10)`, `ArticleContentFetcher.sanitize_url(url)`
- **Usado por**: `wxAsyncNewsGather.py` (backfill_content), `enrichment_worker.py`

> Ver **[ARCHITECTURE.md](ARCHITECTURE.md) § 3** para diagrama detalhado, protocolo e playbook de debug.

#### 🕐 async_tickdb.py
- **Função**: Sistema de agendamento assíncrono
- **Usado por**: wxAsyncNewsGather para ciclos de coleta

---

## 🌍 Sistema de Timezone

### Cobertura Atual
- **96.5% dos artigos** têm `published_at_gmt` populado
- **481+ fontes** cadastradas
- **~55,910 artigos** no banco

### Métodos de Detecção
1. **RFC-5322**: Header `Date:` do feed RSS
2. **pubDate do Feed**: Tag `<pubDate>` com timezone
3. **X-Powered-By**: Header que pode conter timezone do servidor
4. **Fallback**: Timezone configurado manualmente na tabela `gm_sources`

### Verificar Fontes com Timezone
```bash
# Ver fontes que usam timezone automático
sqlite3 predator_news.db "
SELECT source_name, timezone, use_timezone 
FROM gm_sources 
WHERE use_timezone = 1 
ORDER BY source_name;"

# Ver fontes sem timezone
sqlite3 predator_news.db "
SELECT source_name, url 
FROM gm_sources 
WHERE use_timezone = 0;"
```

### Scripts de Backfill (em scripts/timezone/)
- `backfill_published_at_gmt.py`: Backfill geral de timestamps GMT
- `backfill_all_timezones.py`: Backfill completo de todos os grupos
- `backfill_grupo*.py`: Backfill por grupo de fontes
- `validate_*.py`: Validação de timestamps após backfill

---

## 📊 Comandos Úteis

### Estatísticas do Banco
```bash
# Total de artigos
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles;"

# Total de fontes
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_sources;"

# Artigos por dia (últimos 7 dias)
sqlite3 predator_news.db "
SELECT date(published_at_gmt, 'unixepoch') as dia, COUNT(*) as total
FROM gm_articles
WHERE published_at_gmt > unixepoch('now', '-7 days')
GROUP BY dia
ORDER BY dia DESC;"

# Top 10 fontes mais produtivas
sqlite3 predator_news.db "
SELECT source_name, COUNT(*) as total
FROM gm_articles
GROUP BY source_name
ORDER BY total DESC
LIMIT 10;"
```

### Limpeza e Manutenção
```bash
# Remover artigos duplicados (mesmo URL)
sqlite3 predator_news.db "
DELETE FROM gm_articles 
WHERE rowid NOT IN (
    SELECT MIN(rowid) 
    FROM gm_articles 
    GROUP BY url
);"

# Vacuum para recuperar espaço
sqlite3 predator_news.db "VACUUM;"

# Verificar integridade do banco
sqlite3 predator_news.db "PRAGMA integrity_check;"
```

### Backup do Banco de Dados
```bash
# Backup simples
cp predator_news.db predator_news_backup_$(date +%Y%m%d).db

# Backup compactado
sqlite3 predator_news.db ".backup predator_news_backup.db"
gzip predator_news_backup.db
```

---

## 🔧 Troubleshooting

### Problema: Serviço não coleta notícias
```bash
# 1. Verificar status do serviço
sudo systemctl status wxAsyncNewsGather.service

# 2. Ver log de erros
journalctl -u wxAsyncNewsGather.service -p err -n 50

# 3. Ver log completo recente
journalctl -u wxAsyncNewsGather.service -n 100

# 4. Verificar se API está respondendo
curl http://localhost:8765/api/health

# 5. Verificar credenciais
cat .env | grep API_KEY

# 6. Testar conexão manualmente
python -c "from decouple import config; print(config('NEWS_API_KEY_1'))"

# 7. Verificar porta em uso
sudo lsof -i :8765

# 8. Reiniciar o serviço
sudo systemctl restart wxAsyncNewsGather.service
```

### Problema: Fontes retornando erro
```bash
# Ver fontes na blocklist
python check_blocklist.py

# Diagnosticar feed específico
python -c "
import feedparser
url = 'URL_DO_FEED_AQUI'
feed = feedparser.parse(url)
print(f'Status: {feed.status}')
print(f'Entries: {len(feed.entries)}')
"
```

### Problema: Timestamps GMT incorretos
```bash
# Verificar se fonte usa timezone
sqlite3 predator_news.db "
SELECT source_name, use_timezone, timezone 
FROM gm_sources 
WHERE source_name = 'NOME_DA_FONTE';"

# Rodar backfill para fonte específica
# (editar script de backfill para incluir apenas a fonte desejada)
```

### Problema: Interface wxAsyncNewsReaderv6 não abre
```bash
# 1. Verificar dependências
pip list | grep -E "wx|wxPython|wxasync"

# 2. Testar importação
python -c "import wx; import wxasync; print('OK')"

# 3. Verificar display (se SSH)
echo $DISPLAY

# 4. Ver erro completo
python wxAsyncNewsReaderv6.py 2>&1 | head -50
```

---

## 📝 Variáveis de Ambiente (.env)

```bash
# NewsAPI
NEWS_API_KEY_1=sua_chave_aqui
NEWS_API_KEY_2=sua_chave_secundaria

# MediaStack
MEDIASTACK_API_KEY=sua_chave_mediastack
MEDIASTACK_BASE_URL=http://api.mediastack.com/v1

# Database
DB_PATH=predator_news.db

# Intervals (em segundos)
NEWSAPI_CYCLE_INTERVAL=600  # 10 minutos
RSS_CYCLE_INTERVAL=1800     # 30 minutos
```

---

## 🎯 Workflow Típico

### 1. Inicialização do Sistema
```bash
# Iniciar o serviço (coletor + API)
sudo systemctl start wxAsyncNewsGather.service

# Verificar status
sudo systemctl status wxAsyncNewsGather.service

# Testar API
curl http://localhost:8765/api/health

# Ver logs em tempo real
journalctl -u wxAsyncNewsGather.service -f
```

### 2. Usar a Interface de Leitura
```bash
# Abrir o leitor
python wxAsyncNewsReaderv6.py

# Na interface:
# - Marcar fontes de interesse no CheckListBox
# - Clicar "Load Checked" para ver notícias
# - Artigos ordenados por data (mais recentes primeiro)
```

### 3. Monitoramento Periódico
```bash
# Ver logs do serviço em tempo real
journalctl -u wxAsyncNewsGather.service -f

# Ver status do serviço
sudo systemctl status wxAsyncNewsGather.service

# Verificar API
curl http://localhost:8765/api/stats

# Ver últimas notícias coletadas
sqlite3 predator_news.db "
SELECT datetime(published_at_gmt, 'unixepoch'), title 
FROM gm_articles 
ORDER BY published_at_gmt DESC 
LIMIT 5;"
```

### 4. Manutenção Semanal
```bash
# Backup do banco
cp predator_news.db backups/predator_news_$(date +%Y%m%d).db

# Verificar cobertura GMT
python check_gmt_coverage.py

# Ver estatísticas
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles;"
```

---

## 📚 Documentação Adicional

Toda documentação detalhada está em **`docs/`**:

- **README.md**: Visão geral do projeto
- **USE_TIMEZONE_SYSTEM.md**: Sistema de timezone explicado
- **TIMEZONE_BACKFILL_COMPLETE.md**: Relatório de cobertura GMT
- **CONTENT_ENRICHMENT.md**: Sistema de fetch de conteúdo
- **CREDENTIALS_MIGRATION.md**: Migração de credenciais
- E mais 23 documentos de guias, análises e reports

---

## 🛠️ Dependências Principais

```bash
# Core
python >= 3.10
wxPython >= 4.1.0
wxasync
asyncio
aiohttp

# Web Framework
fastapi >= 0.109
uvicorn[standard]
pydantic

# Database
sqlalchemy >= 1.4
sqlite3

# RSS/Parsing  
feedparser
python-dateutil
pytz

# Config
python-decouple

# Content Fetching
requests
beautifulsoup4 (implícito em article_fetcher)
```

---

## 🚦 Status do Sistema

| Componente | Status | Notas |
|------------|--------|-------|
| wxAsyncNewsGatherAPI | ✅ Ativo | Serviço FastAPI unificado (coletor + API) |
| wxAsyncNewsReaderv6 | ✅ Ativo | Interface moderna com Notebook e API polling |
| FastAPI Server | ✅ Port 8765 | Swagger UI em /docs |
| Sistema Timezone | ✅ 96.5% | Cobertura GMT excelente |
| Banco de Dados | ✅ 682k+ artigos | SQLite WAL, ~2 GB (news_db.py singleton) |
| Fontes Ativas | ✅ 1639+ | RSS + NewsAPI + MediaStack |
| Enriquecimento | ✅ Pipeline 3-tiers | cffi→requests→playwright via enrich_try |
| Tradução | ✅ Operacional | Google Translate IPC worker |
| Type Safety | ✅ Clean | Pylance sem erros |
| Projeto  | ✅ Organizado | docs/ + scripts/timezone/ |

---

## 🗂️ news_db.py — Camada de Acesso ao Banco

> Singleton async CRUD. **Toda** acesso ao SQLite vai por aqui.

### Conexões
```python
_c    → aiosqlite (read-write) — INSERT/UPDATE/commit exclusivamente
_rc   → aiosqlite (mode=ro)    — todos os SELECTs; nunca bloqueia escritas
```
WAL mode ativado: leituras concorrentes com escritas — sem lock contention.

### Métodos Read-Only (usam `_rc`)
- `load_sources()`, `load_rss_sources()`
- `get_source_block_status()`, `get_blocked_sources_for_probe()`
- `find_by_title_hash()`
- `fetch_pending_enrichment(limit, enrich_try)` — filtra por tier
- `fetch_pending_translation(batch_size)`
- `fetch_articles_missing_gmt(source_id)`
- `load_blocked_domains()`
- `fetch_article_stats()` — para /api/stats
- `fetch_pending_by_language()` — para /api/monitor
- `fetch_queue_stats()` — queries fundidas, para cache interno

### Cache de Stats
```python
db.cached_stats  # QueueStats TypedDict — atualizado a cada 20s
# Campos: enriched, enrich_pending, enrich_failed,
#         translated, translate_skipped, translate_pending,
#         pending_by_tier {enrich_try: count}, refreshed_at
```

---

## 🔄 Pipeline de Enriquecimento (3 Tiers)

```
enrich_try=0  → cffi_worker      (Chrome TLS, bypass Cloudflare)
                  ↓ falhou
enrich_try=1  → requests_worker  (browser headers)
                  ↓ falhou
enrich_try=2  → playwright_worker (Chromium headless)
```

- `is_enriched=0` + `enrich_try=N` → artigo na fila do tier N
- `is_enriched=1` → enriquecido com sucesso
- `is_enriched=-1` → falhou em todos os tiers (ou fonte bloqueada)
- Cada tier tem semáforo próprio e worker independente
- Stats por tier disponíveis em `/api/queues` → `enrichment.tiers[]`

---

## 📺 Ferramentas de Monitoramento

### monitor_queues.py
```bash
python3 monitor_queues.py [--interval SEGUNDOS] [--history N] [--url URL]
# Padrão: interval=30s, history=10 amostras
```
**Exibe**: totais, enriquecimento por tier (pending/em-voo/resolvido/avançado/descartado),
tradução, velocidades médias (janela deslizante + sessão completa), ETA de drenagem.

**ETA sessão**: taxa líquida (enriquecidas/min − chegadas/min) × pendentes

**ETA marca-d'água**: âncora reset quando pending *sobe* (burst); fica fixo durante drenagem
para dar taxa estável. Drain rate = (wm_pending − cur_pend) / elapsed.

### watch_translations.py
```bash
python3 watch_translations.py
```
Monitora tradução + tiers de enriquecimento via `/api/monitor`.

---

## 📡 Endpoints API

| Endpoint | Cache | Descrição |
|----------|-------|-----------|
| `/api/health` | não | Health check |
| `/api/articles` | não | Artigos por timestamp/source |
| `/api/sources` | não | Lista de fontes |
| `/api/stats` | não | total, last_24h, last_hour, total_sources |
| `/api/queues` | 20s | Enriquecimento + tradução + tiers detalhados |
| `/api/monitor` | 20s | Stats completas + pending_by_language |
| `/api/latest_timestamp` | não | Último inserted_at_ms |

O campo `stats_age_s` em `/api/queues` indica há quantos segundos o cache foi atualizado.

---


**Última atualização**: 11 de abril de 2026
**Autor**: jamaj69
**Repositório**: github.com/jamaj69/wxNews
