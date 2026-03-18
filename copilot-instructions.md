# wxNews - Instruções do Sistema

Sistema de agregação e leitura de notícias com coleta automática via RSS/NewsAPI/MediaStack e interface gráfica moderna com FastAPI backend.

---

## 🚀 Gerenciamento do Serviço wxAsyncNewsGatherAPI

O serviço está configurado como **systemd service** e roda tanto o coletor quanto a API REST.

### Iniciar o Serviço
```bash
sudo systemctl start wxAsyncNewsGatherAPI.service
```

### Verificar Status do Serviço
```bash
sudo systemctl status wxAsyncNewsGatherAPI.service
```

### Parar o Serviço
```bash
sudo systemctl stop wxAsyncNewsGatherAPI.service
```

### Reiniciar o Serviço
```bash
sudo systemctl restart wxAsyncNewsGatherAPI.service
```

### Ver Logs em Tempo Real
```bash
journalctl -u wxAsyncNewsGatherAPI.service -f
```

### Ver Últimas Linhas do Log (últimas 50)
```bash
journalctl -u wxAsyncNewsGatherAPI.service -n 50
```

### Ver Logs com Erro
```bash
journalctl -u wxAsyncNewsGatherAPI.service -p err
```

### Habilitar Serviço no Boot
```bash
sudo systemctl enable wxAsyncNewsGatherAPI.service
```

### Desabilitar Serviço no Boot
```bash
sudo systemctl disable wxAsyncNewsGatherAPI.service
```

### Recarregar Configuração do Systemd (após editar .service)
```bash
sudo systemctl daemon-reload
sudo systemctl restart wxAsyncNewsGatherAPI.service
```

### Ver Arquivo de Unidade do Serviço
```bash
systemctl cat wxAsyncNewsGatherAPI.service
```

### Execução Manual (para debug)
```bash
cd /home/jamaj/src/python/pyTweeter
source /home/python/pyenv/bin/activate
python wxAsyncNewsGatherAPI.py
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

### Ver Logs em Tempo Real
```bash
# Via systemd journal
journalctl -u wxAsyncNewsGatherAPI.service -f

# Ver últimas 100 linhas
journalctl -u wxAsyncNewsGatherAPI.service -n 100

# Ver apenas erros
journalctl -u wxAsyncNewsGatherAPI.service -p err -f

# Ver logs de hoje
journalctl -u wxAsyncNewsGatherAPI.service --since today
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
├── wxAsyncNewsGatherAPI.py       # 🚀 Serviço principal (FastAPI + Coletor)
├── wxAsyncNewsGather.py          # 📡 Módulo coletor (usado pelo API)
├── wxAsyncNewsReaderv6.py        # 📱 Interface gráfica moderna
├── article_fetcher.py            # 📄 Fetcher de conteúdo de artigos
├── async_tickdb.py               # ⏰ Sistema de agendamento
│
├── predator_news.db              # 💾 Banco de dados SQLite (~55k artigos)
├── .env                          # 🔐 Credenciais (NEWS_API_KEY_1, etc)
├── requirements-fastapi.txt      # 📦 Dependências FastAPI
├── requirements.txt              # 📦 Todas as dependências
└── .gitignore                    # 🚫 Exclusões do git
```

### Arquivos Principais

#### 🚀 wxAsyncNewsGatherAPI.py (Serviço Principal)
- **Função**: Aplicação FastAPI unificada com coletor e API REST
- **Recursos**:
  - FastAPI server na porta 8765
  - Coleta paralela: NewsAPI, RSS feeds, MediaStack
  - REST API com endpoints:
    - GET /api/health - Health check
    - GET /api/articles - Query articles com timestamp
    - GET /api/sources - Lista de fontes
    - GET /api/stats - Estatísticas de coleta
    - GET /api/latest_timestamp - Último timestamp
    - GET /docs - Swagger UI interativo
  - Documentação automática (OpenAPI)
  - Systemd service com auto-restart
- **Arquivo**: `/etc/systemd/system/wxAsyncNewsGatherAPI.service`

#### 📡 wxAsyncNewsGather.py (Módulo Coletor)
- **Função**: Módulo de coleta de notícias (importado pelo API)
- **Recursos**:
  - Coleta assíncrona com aiohttp
  - Sistema de timezone automático (96.5% cobertura GMT)
  - Detecção de timezone via RFC-5322, feed pubDate, e X-Powered-By
  - Blocklist para fontes problemáticas
  - Fetch automático de conteúdo de artigos
  - Deduplicação por URL
- **Config**: Usa variáveis do `.env` (API_KEY1, API_KEY2, DB_PATH, etc)
- **Nota**: Não executar diretamente, usar via wxAsyncNewsGatherAPI.py

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
- **Engine**: SQLite
- **Tabelas principais**:
  - `gm_articles`: Artigos coletados
  - `gm_sources`: Fontes de notícias (481+)
  - `gm_newsapi_sources`: Fontes do NewsAPI
- **Campos importantes em gm_articles**:
  - `title`, `url`, `description`, `author`
  - `published_at`: Timestamp original
  - `published_at_gmt`: Timestamp convertido para GMT (Unix epoch)
  - `source_name`, `id_source`
  - `content`: Conteúdo completo do artigo (quando disponível)
  - `use_timezone`: Flag indicando se usa sistema de timezone

#### ⚙️ article_fetcher.py
- **Função**: Busca conteúdo completo de artigos
- **Método**: `fetch_article_content(url, user_agent)`
- **Usado por**: wxAsyncNewsGather durante coleta

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
sudo systemctl status wxAsyncNewsGatherAPI.service

# 2. Ver log de erros
journalctl -u wxAsyncNewsGatherAPI.service -p err -n 50

# 3. Ver log completo recente
journalctl -u wxAsyncNewsGatherAPI.service -n 100

# 4. Verificar se API está respondendo
curl http://localhost:8765/api/health

# 5. Verificar credenciais
cat .env | grep API_KEY

# 6. Testar conexão manualmente
python -c "from decouple import config; print(config('NEWS_API_KEY_1'))"

# 7. Verificar porta em uso
sudo lsof -i :8765

# 8. Reiniciar o serviço
sudo systemctl restart wxAsyncNewsGatherAPI.service
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
sudo systemctl start wxAsyncNewsGatherAPI.service

# Verificar status
sudo systemctl status wxAsyncNewsGatherAPI.service

# Testar API
curl http://localhost:8765/api/health

# Ver logs em tempo real
journalctl -u wxAsyncNewsGatherAPI.service -f
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
journalctl -u wxAsyncNewsGatherAPI.service -f

# Ver status do serviço
sudo systemctl status wxAsyncNewsGatherAPI.service

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
| Banco de Dados | ✅ 55k+ artigos | SQLite (predator_news.db) |
| Fontes Ativas | ✅ 480+ | RSS + NewsAPI + MediaStack |
| Type Safety | ✅ Clean | Pylance sem erros |
| Projeto  | ✅ Organizado | docs/ + scripts/timezone/ |

---

**Última atualização**: 2 de março de 2026
**Autor**: jamaj69
**Repositório**: github.com/jamaj69/wxNews
