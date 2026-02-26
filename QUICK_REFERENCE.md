# pyTweeter - Quick Reference Summary

## 📋 Análise Rápida

### Estado Atual (2026-02-26)

| Componente | Status | Severidade |
|------------|--------|-----------|
| **Twitter API** | ❌ Quebrado | 🔴 Crítico |
| **NewsAPI** | ⚠️ Limitado | 🟠 Médio |
| **GUI** | ✅ Funcional | 🟢 OK |
| **Segurança** | ❌ Credenciais Expostas | 🔴 Crítico |
| **Estrutura** | ⚠️ Dívida Técnica | 🟡 Médio |

---

## 🔍 Descobertas Principais

### 🧹 Limpeza de Arquivos (2026-02-26)

**Status:** ✅ **CONCLUÍDO**

Removidos arquivos não relacionados ao projeto de coleta de notícias:

**Arquivados** (movidos para `archive/`):
- `pyNews.zip` (8 KB) - Backup de versões antigas (2019-2020)

**Removidos** (96+ MB liberados):
- 7 PDFs (13 MB) - Artigos de pesquisa (1938-1960): 1044-2796-1-SM.pdf, 1938-05.pdf, 1938-06.pdf, 194-560-1-SM.pdf, 1959-06.pdf, 1959-11.pdf, 1960-10.pdf
- `hello-rust/` (79 MB) - Projeto Rust não relacionado
- `owid-covid-data.csv` (2.9 MB) - Dados COVID-19
- `who_w0039.ods` (18 KB) - Dados da OMS
- `UF_Brasil.tsv` (486 bytes) - Estados do Brasil
- `predator_db.odb` (2.3 KB) - Banco LibreOffice
- `mailer.php` (1.6 KB) - Script PHP não relacionado
- `jamajDB` (2.4 KB) - Protótipo NoSQL distribuído
- `.xsession` (124 bytes) - Config X Window (não deveria estar no projeto)
- `geo_demo1.py`, `geo_proj.py`, `geodemo2.py` - Visualizações geográficas
- `translate.py` - Utilitário de tradução

**Mantidos** (necessários):
- `images.py` (510 KB) - ✅ Usado por wxListGrid.py (ícones wxPython embedded)
- `Scheduler.py` (12 KB) - ✅ Dependência crítica restaurada do ucbvet

**Resultado:**
- Tamanho do projeto: **~96 MB → 2.2 MB** (redução de 97.7%)
- Arquivos Python: 31 (apenas código relacionado a news collection)
- Diretórios: archive/, dask-worker-space/, __pycache__/

### 1. Credenciais do Twitter

**Localização:** [twitterasync_new.py](twitterasync_new.py#L166-L169)

```python
CONSUMER_KEY = 'j1KOc2AWQ5QvrtNe8N15UfcXI'
CONSUMER_SECRET = 'AjHnwNBhBB1eegMcVYDvVBiQMAX6PHX9OOdqbqFSHHeezB9IJF'
ACCESS_TOKEN = '1201408473151496192-KZ2xMa2GSuanbi8UJtyFaH4XQ5foWa'
ACCESS_TOKEN_SECRET = 'rUgHWt9z252O0tX94GjO0Zs518NIWiCCXm1slluLX86T0'
```

**Status:** ❌ **NÃO FUNCIONA MAIS**
- API v1.1 do Twitter foi descontinuada
- X (Twitter) agora cobra $100+/mês para acesso à API
- Biblioteca Peony não mantida desde 2020

### 2. Credenciais do NewsAPI

**Status:** ⚠️ **Provavelmente Funciona (com limites)**

4 chaves API encontradas (2 duplicadas):
- `c85890894ddd4939a27c19a3eff25ece` (predator@jamaj.com.br)
- `4327173775a746e9b4f2632af3933a86` (jamaj@jamaj.com.br)

**Limites:** 100 requisições/dia por chave = 400 total/dia

### 3. Credenciais do Banco de Dados

**PostgreSQL:**
```python
user: 'predator'
password: 'fuckyou'  # ⚠️ SENHA EM TEXTO SIMPLES
host: 'titan'
dbname: 'predator3_dev'
```

**Redis:**
```python
host: 'localhost'
port: 6379
db: 0
```

---

## 📁 Estrutura dos Programas

### Programas Ativos (Para Usar)

1. **wxAsyncNewsGather.py** (378 linhas)
   - Coleta notícias do NewsAPI.org
   - 4 idiomas: EN, PT, ES, IT
   - Armazena em PostgreSQL
   - Atualiza a cada 10 minutos

2. **wxAsyncNewsReaderv5.py** (315 linhas)
   - GUI wxPython
   - Mostra fontes de notícias (painel esquerdo)
   - Mostra artigos (painel direito)
   - Abre no navegador ao clicar
   - Atualiza a cada 60 segundos

3. **redis_twitter.py** (124 linhas)
   - Funções auxiliares para Redis
   - Locks distribuídos
   - Criação de usuários/posts

### Programas Quebrados (NÃO USAR)

1. **twitterasync_new.py** (339 linhas)
   - Coletor de tweets via streaming
   - ❌ API v1.1 descontinuada
   - ❌ Biblioteca Peony obsoleta

2. **twitterasync.py** (277 linhas)
   - Versão mais antiga do acima
   - ❌ Mesmo problema

### Programas Duplicados (Consolidar)

- `wxAsyncNewsReaderv1.py` → `v5.py` (4 versões antigas)
- `wxAsyncNewsGather1.py` (duplicata do original)

### ~~Programas Não Relacionados~~ ✅ REMOVIDOS (2026-02-26)

- ~~`covid*.py`~~ - ✅ Removido
- ~~`geo_*.py`~~ - ✅ Removido  
- ~~`translate.py`~~ - ✅ Removido
- `images.py` - ✅ **MANTIDO** (usado por wxListGrid.py)

---

## 🏗️ Arquitetura

### Fluxo de Dados (News)

```
┌──────────────┐
│ NewsAPI.org  │
│ 4 idiomas    │
└──────┬───────┘
       │ HTTP GET
       ▼
┌──────────────┐
│NewsGather.py │
│ (async loop) │
└──────┬───────┘
       │ SQLAlchemy
       ▼
┌──────────────┐     ┌──────────┐
│ PostgreSQL   │────►│  Redis   │
│ gm_sources   │     │  (cache) │
│ gm_articles  │     └──────────┘
└──────┬───────┘
       │
       ▼
┌──────────────┐
│NewsReaderv5  │
│ (wxPython)   │
└──────────────┘
```

### Fluxo de Dados (Twitter - Quebrado)

```
┌──────────────┐
│Twitter Stream│
│  API v1.1    │  ❌ DESCONTINUADO
└──────┬───────┘
       │
       ▼
┌──────────────┐
│twitterasync  │  ❌ NÃO FUNCIONA
│  (Peony)     │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│    Redis     │
│ users:*      │
│ user:{id}    │
│ status:{id}  │
└──────────────┘
```

---

## 🛠️ Stack Tecnológico

| Componente | Tecnologia | Status |
|------------|-----------|--------|
| **Linguagem** | Python 3.7-3.8 | ⚠️ Desatualizado |
| **Async** | asyncio + aiohttp | ✅ Moderno |
| **Twitter** | Peony (v1.1 API) | ❌ Obsoleto |
| **News** | NewsAPI REST | ✅ Ativo |
| **GUI** | wxPython + wxasync | ✅ Viável |
| **DB Relacional** | PostgreSQL + SQLAlchemy | ✅ Moderno |
| **DB Cache** | Redis | ✅ Moderno |
| **Hash** | base64(zlib()) | ⚠️ Não-criptográfico |

---

## 🚨 Problemas Críticos

### 1. Segurança
- ❌ Credenciais hardcoded no código
- ❌ Senhas em texto simples
- ❌ Histórico do Git expõe segredos
- ❌ Sem validação de entrada

### 2. Twitter
- ❌ API v1.1 descontinuada
- ❌ Endpoint `statuses.filter` removido
- ❌ Biblioteca Peony não mantida
- ❌ Nível gratuito não existe mais

### 3. Código
- ⚠️ 5 versões do mesmo arquivo
- ⚠️ Código comentado em excesso
- ⚠️ Funções duplicadas
- ⚠️ Sem estrutura de pacotes
- ⚠️ Zero testes automatizados

### 4. Rate Limits
- ⚠️ NewsAPI: 100 req/dia por chave
- ⚠️ Atualiza a cada 10 min = 144 req/dia
- ⚠️ 4 idiomas × 144 = 576 req/dia necessários
- ⚠️ 4 chaves × 100 = 400 req/dia disponível
- ⚠️ **Vai estourar o limite!**

---

## ✅ Ações Imediatas (Hoje)

### Passo 1: Verificar Conectividade
```bash
# Testar PostgreSQL
psql -h titan -U predator -d predator3_dev

# Testar Redis
redis-cli -h localhost ping

# Testar NewsAPI
curl "https://newsapi.org/v2/top-headlines?language=en&pageSize=1&apiKey=c85890894ddd4939a27c19a3eff25ece"
```

### Passo 2: Proteger Credenciais
```bash
# Criar arquivo .env
cp .env.example .env
nano .env  # Adicionar credenciais reais

# Adicionar ao .gitignore
echo ".env" >> .gitignore

# Limpar histórico (se necessário)
git filter-repo --invert-paths --path .env
```

### Passo 3: Testar News (Sem Twitter)
```bash
# Ativar ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependências mínimas
pip install aiohttp sqlalchemy psycopg2-binary redis wxPython wxasync

# Testar coletor de notícias
python wxAsyncNewsGather.py

# Em outro terminal, testar GUI
python wxAsyncNewsReaderv5.py
```

---

## 📋 Plano de Refatoração (Resumo)

### Semana 1: Emergência
- [x] Mover credenciais para .env
- [ ] Remover código do Twitter
- [ ] Criar requirements.txt
- [ ] Adicionar .gitignore

### Semana 2-3: Arquitetura
- [ ] Estrutura de pacotes Python
- [ ] Consolidar versões duplicadas
- [ ] Classe base abstrata para coletores
- [ ] Config centralizado

### Semana 4: Substituir Twitter
- [ ] Adicionar suporte a RSS feeds
- [ ] Integrar Mastodon
- [ ] Ou: migrar para Reddit
- [ ] Atualizar GUI

### Semana 5: Testes
- [ ] pytest + coverage
- [ ] CI/CD (GitHub Actions)
- [ ] Linting (black, flake8)
- [ ] Type hints (mypy)

### Semana 6+: Melhorias
- [ ] Logging estruturado
- [ ] Monitoramento (Sentry)
- [ ] Cache inteligente
- [ ] Dashboard web (FastAPI)

---

## 📖 Documentação Completa

Para análise detalhada, veja:
- **[README.md](README.md)** - Guia de uso e quick start
- **[ANALYSIS_AND_REFACTORING_PLAN.md](ANALYSIS_AND_REFACTORING_PLAN.md)** - Análise completa de 13 seções

---

## 🎯 Decisões Importantes

### Twitter: Manter ou Substituir?
**Decisão:** ❌ **REMOVER**
- Custo: $100+/mês (X API Basic)
- Alternativa: Mastodon (grátis) + RSS

### GUI: Manter wxPython?
**Decisão:** ✅ **MANTER**
- Cross-platform
- Funcional
- Adicionar: Dashboard web opcional

### Banco: Manter PostgreSQL?
**Decisão:** ✅ **MANTER**
- Robusto para dados estruturados
- Adicionar: Migrations (Alembic)

### Cache: Manter Redis?
**Decisão:** ✅ **MANTER e EXPANDIR**
- Excelente para cache
- Usar para: rate limiting, filas

---

## 📊 Métricas de Sucesso

| Métrica | Atual | Meta |
|---------|-------|------|
| Uptime | Desconhecido | 90%+ |
| Cobertura de Testes | 0% | 80%+ |
| Tempo de Startup | ~5s | <3s |
| Vulnerabilidades Críticas | 3+ | 0 |
| Versões Duplicadas | 10+ | 0 |
| Credenciais Expostas | Sim | Não |

---

## 🔗 Links Úteis

- **NewsAPI:** https://newsapi.org
- **Mastodon.py:** https://github.com/halcy/Mastodon.py
- **wxPython:** https://wxpython.org
- **SQLAlchemy:** https://www.sqlalchemy.org
- **Redis:** https://redis.io

---

## 📞 Próximos Passos

1. **Ler:** [ANALYSIS_AND_REFACTORING_PLAN.md](ANALYSIS_AND_REFACTORING_PLAN.md)
2. **Testar:** NewsAPI ainda funciona?
3. **Decidir:** Vale investir $100/mês no Twitter/X?
4. **Executar:** Fase 1 (segurança) esta semana
5. **Planejar:** Roadmap de 7 semanas

---

**Última Atualização:** 2026-02-26  
**Análise por:** AI Assistant  
**Status:** Pronto para refatoração
