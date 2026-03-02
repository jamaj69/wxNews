# Sistema use_timezone - Documentação

## 📋 Visão Geral

Foi adicionado um campo booleano `use_timezone` na tabela `gm_sources` para controlar explicitamente quais fontes podem ter seu timezone aplicado aos artigos.

## 🎯 Objetivo

Evitar que o sistema aplique timezone automaticamente de fontes não confirmadas, garantindo que apenas fontes validadas manualmente tenham seu timezone usado para converter timestamps.

## 🗄️ Mudanças no Banco de Dados

### Nova Coluna
```sql
ALTER TABLE gm_sources ADD COLUMN use_timezone INTEGER DEFAULT 0;
```

- **Tipo**: INTEGER (0 ou 1, booleano no SQLite)
- **Default**: 0 (desabilitado)
- **Significado**:
  - `0` = NÃO usar timezone da fonte (padrão seguro)
  - `1` = Usar timezone da fonte (confirmada manualmente)

### Fontes Confirmadas (use_timezone = 1)

As seguintes fontes foram marcadas como confirmadas:

| Fonte | Timezone | Artigos | Cobertura |
|-------|----------|---------|-----------|
| All News (Investing.com) | UTC+00:00 | 462 | 100% |
| Exame | UTC-03:00 | 319 | 100% |
| Notícias ao Minuto - Mundo | UTC+00:00 | 704 | 100% |
| Notícias ao Minuto - País | UTC+00:00 | 699 | 100% |
| Notícias ao Minuto - Tech | UTC+00:00 | 700 | 100% |
| Notícias ao Minuto - Brasil | UTC-03:00 | 4 | 100% |
| The Hindu (3 feeds) | UTC+05:30 | 969 | 100% |
| Economico | UTC+00:00 | 83 | 100% |

**Total**: 10 fontes confirmadas com 100% de cobertura GMT

## ⚙️ Como o Sistema Funciona

### 1. Carregamento de Fontes

Os métodos `InitArticles()` e `reload_sources()` agora carregam o campo `use_timezone`:

```python
sources[source_id] = {
    'id_source': source_id,
    'name': source[1],
    # ... outros campos ...
    'timezone': source[9],
    'use_timezone': source[10],  # NOVO CAMPO
    'articles': {}
}
```

### 2. Conversão de Timestamps

A função `normalize_timestamp_to_utc()` foi modificada com novo parâmetro:

```python
def normalize_timestamp_to_utc(timestamp_str, source_timezone=None, use_source_timezone=False):
```

**Prioridades de Conversão**:

1. **Timezone no artigo** (RFC 2822, ISO 8601): SEMPRE usado (maior prioridade)
2. **GMT/UTC explícito no texto**: Trata como UTC+00:00
3. **Timezone da fonte** (SE `use_source_timezone=True`): Aplica timezone configurado
4. **Nenhum timezone disponível**: Retorna `None` (não converte)

### 3. Processamento de Artigos

Nos coletores (RSS, NewsAPI, MediaStack), o sistema agora checa:

```python
use_tz = source.get('use_timezone', 0)
published_gmt, detected_tz = normalize_timestamp_to_utc(
    published, 
    source_tz, 
    use_source_timezone=(use_tz == 1)  # Só aplica se confirmado
)
```

### 4. Backfill Automático

O backfill automático agora é **condicional**:

```python
if source_tz != consistent_tz:
    await self.update_source_timezone(source_id, consistent_tz)
    
    # Só faz backfill se use_timezone = 1
    if use_tz == 1:
        await self.backfill_missing_gmt_for_source(source_id, consistent_tz)
    else:
        # Log informativo: precisa confirmação manual
        self.logger.info(f"⏸️  [{source_name}] use_timezone=0, skipping automatic backfill")
```

## 🔧 Scripts Utilitários

### 1. Marcar Fonte como Confirmada

```bash
# Script: /tmp/confirm_source_timezone.py
python3 /tmp/confirm_source_timezone.py <source_id>
```

### 2. Desmarcar Fonte

```bash
python3 /tmp/confirm_source_timezone.py <source_id> --unconfirm
```

### 3. Listar Fontes Confirmadas

```bash
sqlite3 predator_news.db "SELECT id_source, name, timezone FROM gm_sources WHERE use_timezone = 1;"
```

### 4. Verificar Cobertura das Confirmadas

```bash
python3 /tmp/test_use_timezone.py
```

## 📊 Workflow de Confirmação de Novas Fontes

### Passo 1: Investigar Fonte
```bash
cd /home/jamaj/src/python/pyTweeter
python3 check_gmt_coverage.py source "Nome da Fonte"
```

### Passo 2: Analisar Timezone
- Verificar URL da fonte
- Baixar RSS/feed ao vivo
- Analisar timestamps
- Inferir timezone com evidências

### Passo 3: Confirmar Timezone no Banco
```sql
-- Atualizar timezone
UPDATE gm_sources 
SET timezone = 'UTC+XX:XX' 
WHERE id_source = 'fonte-id';

-- Marcar como confirmada
UPDATE gm_sources 
SET use_timezone = 1 
WHERE id_source = 'fonte-id';
```

### Passo 4: Fazer Backfill
```bash
# Criar script de backfill (baseado em /tmp/backfill_investing_com.py)
python3 /tmp/backfill_[nome-fonte].py
```

### Passo 5: Verificar
```bash
python3 check_gmt_coverage.py source "Nome da Fonte"
```

## ⚠️ Segurança e Conservadorismo

### Filosofia do Sistema

- **Default seguro**: `use_timezone = 0` (não assumir nada)
- **Confirmação manual**: Apenas fontes validadas têm `use_timezone = 1`
- **Evidências necessárias**: Não usar timezone sem análise prévia
- **Qualidade > Quantidade**: Melhor 95% de cobertura com certeza do que 98% com suposições

### Quando NÃO Confirmar uma Fonte

❌ Timezone inferido sem evidências fortes  
❌ Site global sem identidade regional clara  
❌ Feeds com timestamps inconsistentes  
❌ Fontes com poucos artigos (< 30) sem backtest  
❌ APIs sem documentação de timezone  

### Quando Confirmar uma Fonte

✅ Site com identidade regional clara (país específico)  
✅ Timezone detectado consistentemente em múltiplos artigos  
✅ Análise de time differential corrobora timezone  
✅ Documentação/padrão da indústria confirma timezone  
✅ Backfill manual já executado e verificado  

## 📈 Impacto no Sistema

### Antes
- Sistema tentava detectar timezone automaticamente
- Poderia aplicar timezone incorreto
- Backfill automático para todas as fontes
- Risco de conversões erradas

### Depois
- Controle explícito por fonte
- Apenas fontes confirmadas usam timezone
- Backfill automático apenas para confirmadas
- Maior confiança nos dados

### Estatísticas Atuais

- **Total de fontes**: 871
- **Fontes confirmadas**: 10 (1.1%)
- **Cobertura geral**: 94.78%
- **Artigos com GMT**: 51,816 / 54,671
- **Fontes confirmadas**: 100% de cobertura (3,939 artigos)

## 🔄 Próximos Passos

1. **zazoom** (Itália, 405 artigos) - candidato para confirmação
2. **Nature News** (91 artigos) - timestamps sem hora, não pode ser corrigido
3. **Outras fontes** (< 50 artigos cada) - avaliar caso a caso

## 🐛 Troubleshooting

### Artigos não estão sendo convertidos

1. Verificar se fonte tem `use_timezone = 1`:
```sql
SELECT use_timezone FROM gm_sources WHERE id_source = 'fonte-id';
```

2. Verificar se timezone está definido:
```sql
SELECT timezone FROM gm_sources WHERE id_source = 'fonte-id';
```

3. Verificar logs do coletor:
```bash
journalctl -u wxNews -f | grep "fonte-nome"
```

### Backfill automático não está funcionando

O backfill automático **só funciona** se:
- `use_timezone = 1` no banco
- Todos os artigos do feed têm timezone consistente
- Timezone detectado é diferente do configurado

Se essas condições não são atendidas, fazer backfill manual.

## 📝 Notas Finais

Este sistema garante que apenas fontes **explicitamente confirmadas** tenham seu timezone aplicado aos artigos, evitando conversões incorretas e mantendo a integridade dos dados.

Para adicionar novas fontes ao sistema confirmado, sempre seguir o workflow de confirmação documentado acima.
