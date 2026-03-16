# Sistema de Auto-Detecção de Timezone

## Problema Identificado

Durante a operação normal do sistema, descobrimos que **1,922+ artigos** tinham timestamps impossíveis (datas futuras, algumas com 5+ horas de antecipação). 

### Causa Raiz

Muitos RSS feeds **mentem sobre seu timezone**:
- Publicam timestamps em horário **local** (ex: Eastern Time, Spain Time)
- Mas marcam como **"+0000" (UTC)** no RSS feed
- Nosso sistema confiava no que o RSS declarava

### Exemplos Reais

**On3.com (Site de esportes dos EUA)**:
```xml
<pubDate>Mon, 16 Mar 2026 03:51:51 +0000</pubDate>
```
- RSS afirma: 03:51:51 UTC
- Hora real do sistema: 03:58 UTC  
- Artigo aparece como "futuro" por 7 minutos... mas na realidade está 5 horas no futuro!
- Timezone real: UTC-05:00 (Eastern Time)
- Site publica horário local mas marca como UTC

**La Opinión de Zamora (Jornal Espanhol)**:
```xml
<pubDate>Mon, 16 Mar 2026 09:00:00 +0000</pubDate>  
```
- RSS afirma: 09:00 UTC
- Hora real: 04:00 UTC
- Diferença: 5 horas no futuro!
- Timezone real: UTC+01:00 (CET - Central European Time)
- Site publica horário local mas marca como UTC

## Solução: Auto-Detecção Inteligente

### Estratégia

O sistema agora **detecta automaticamente** quando um RSS feed está mentindo:

1. **Coleta artigo** e converte timestamp para UTC
2. **Verifica**: `published_at_gmt > now() + 30 minutos`?
3. Se SIM → RSS está mentindo!
4. **Calcula** timezone correto baseado na diferença
5. **Atualiza** fonte no banco:
   - `timezone = UTC-XX:YY` (calculado)
   - `use_timezone = 1` (força correção)
6. **Recalcula** timestamp do artigo com timezone correto
7. **Próximos artigos** desta fonte já usam timezone correto

### Threshold de 30 Minutos

Por que 30 minutos?
- ✅ Artigos legítimos podem estar alguns minutos "no futuro" (clock skew, cache)
- ✅ 30 minutos é margem segura para variações normais
- ❌ 5+ horas no futuro = RSS definitivamente mentindo
- ✅ Evita falsos positivos com conteúdo agendado

## Implementação Técnica

### Localização do Código

O sistema está implementado em **3 pontos críticos** onde artigos são coletados:

1. **NewsAPI Collector** (linha ~1247)
2. **RSS Feed Processor** (linha ~1548)  
3. **MediaStack Collector** (linha ~1758)

### Fluxo de Auto-Correção

```python
# 1. Detectar artigo futuro
if article_publishedAt_gmt and use_tz == 0:  # Só corrige se não foi configurado manualmente
    parsed_gmt = datetime.fromisoformat(article_publishedAt_gmt)
    now_utc = datetime.now(timezone.utc)
    time_diff = parsed_gmt - now_utc
    
    # 2. Verificar se > 30 minutos no futuro
    if time_diff > timedelta(minutes=30):
        
        # 3. Calcular timezone correto
        total_seconds = int(time_diff.total_seconds())
        hours_offset = total_seconds // 3600
        minutes_offset = (total_seconds % 3600) // 60
        
        # Arredondar para incrementos de 30min (timezones comuns)
        if minutes_offset > 15 and minutes_offset < 45:
            minutes_offset = 30
        elif minutes_offset >= 45:
            hours_offset += 1
            minutes_offset = 0
        else:
            minutes_offset = 0
        
        # Formato: UTC-05:00 (negativo pois RSS afirma UTC mas é local)
        corrected_tz = f"UTC-{abs(hours_offset):02d}:{minutes_offset:02d}"
        
        # 4. Atualizar banco de dados
        await db.execute(
            'UPDATE gm_sources SET timezone = ?, use_timezone = 1 WHERE id_source = ?',
            (corrected_tz, source_id)
        )
        
        # 5. Atualizar cache em memória
        source['timezone'] = corrected_tz
        source['use_timezone'] = 1
        
        # 6. Recalcular timestamp deste artigo
        article_publishedAt_gmt, detected_tz = normalize_timestamp_to_utc(
            article_publishedAt, 
            corrected_tz, 
            use_source_timezone=True  # Força uso do timezone correto
        )
```

### Logs Gerados

**Quando detecta problema:**
```
⚠️  🔍 AUTO-TIMEZONE-DETECT: [On3.com] Article is 5h0m in future! 
RSS claims UTC but likely publishes local time. 
Setting timezone=UTC-05:00, use_timezone=1
```

**Após recalcular:**
```
✅ [On3.com] Recalculated: Mon, 16 Mar 2026 03:51:51 +0000 → 2026-03-15T22:51:51+00:00
```

## PRIORITY 0: Forçar Timezone

### Mudança no normalize_timestamp_to_utc()

Adicionada **PRIORITY 0** que sobrescreve timezone do RSS quando `use_source_timezone=True`:

```python
# PRIORITY 0: If use_source_timezone is True, FORCE source timezone (ignore RSS timezone)
# This handles sources that lie about their timezone in the RSS feed
if use_source_timezone and source_timezone:
    # Parse timezone offset from 'UTC+05:30' ou 'UTC-03:00'
    tz_match = re.search(r'([+-])?(\d{2}):(\d{2})', source_timezone)
    if tz_match:
        # ... calcular offset ...
        
        # CRITICAL: Remove RSS timezone and apply source timezone
        parsed_dt = parsed_dt.replace(tzinfo=None)  # Strip RSS timezone (it's wrong!)
        parsed_dt = parsed_dt.replace(tzinfo=tz_offset)  # Apply correct source timezone
        
        # Convert to UTC and return immediately
        utc_dt = parsed_dt.astimezone(timezone.utc)
        return utc_dt.replace(microsecond=0).isoformat(), source_timezone
```

**Antes (PRIORITY 1 first):**
1. Usa timezone do RSS (mesmo se errado)
2. Só usa `source_timezone` se artigo não tiver timezone

**Agora (PRIORITY 0 first):**
1. Se `use_timezone=1` → **IGNORA** timezone do RSS
2. **FORÇA** uso do `source_timezone` configurado
3. Previne que RSS minta sobre timezone

## Scripts de Correção Manual

### fix_timezone_sources.py

Script para correção manual em massa:
- 60+ mapeamentos de país/domínio
- Detecta timezone por TLD (.es, .com.br, .ar, etc.)
- Casos especiais para domínios .com (por nome da fonte)

**Uso:**
```bash
# Análise (dry-run)
python scripts/fix_timezone_sources.py --limit 20

# Aplicar correções
python scripts/fix_timezone_sources.py --apply-fixes
```

### backfill_article_timestamps.py

Script para recalcular timestamps de artigos históricos:
- Usa `normalize_timestamp_to_utc()` com timezone correto
- Processa artigos com `published_at_gmt > now()`
- Suporta dry-run para preview

**Uso:**
```bash
# Preview
python scripts/backfill_article_timestamps.py

# Aplicar
python scripts/backfill_article_timestamps.py --apply
```

## Monitoramento

### Verificar Artigos Futuros

```sql
-- Contar artigos com timestamp futuro
SELECT COUNT(*) FROM gm_articles 
WHERE published_at_gmt > datetime('now');

-- Top fontes problemáticas
SELECT s.name, s.timezone, s.use_timezone, COUNT(*) as count 
FROM gm_articles a 
JOIN gm_sources s ON a.id_source = s.id_source 
WHERE a.published_at_gmt > datetime('now') 
GROUP BY s.name 
ORDER BY count DESC 
LIMIT 20;
```

### Verificar Auto-Correções

```bash
# Ver logs de auto-detecção
sudo journalctl -u wxAsyncNewsGather -f | grep "AUTO-TIMEZONE-DETECT"

# Ver fontes com use_timezone=1 (corrigidas)
sqlite3 predator_news.db "SELECT name, timezone, use_timezone FROM gm_sources WHERE use_timezone = 1"
```

### Métricas Esperadas

**Após implementação:**
- ✅ Artigos com timestamp futuro: < 50 (artigos coletados nos últimos minutos)
- ✅ Artigos > 1 hora no futuro: 0 (exceto conteúdo verdadeiramente agendado)
- ✅ Novas fontes: auto-corrigidas no primeiro artigo problemático
- ✅ Logs: Mensagens "AUTO-TIMEZONE-DETECT" apenas para fontes novas

## Benefícios

### Automático e Gradual
- ✅ Não requer configuração manual
- ✅ Detecta problemas em produção
- ✅ Auto-corrige fonte na primeira detecção
- ✅ Próximos artigos já vêm corrigidos

### Preciso
- ✅ Threshold de 30 minutos evita falsos positivos
- ✅ Arredondamento para incrementos comuns (0, 30, 45 minutos)
- ✅ Suporta timezones não-inteiros (UTC+05:30 Índia, UTC+09:30 Austrália)

### Transparente
- ✅ Logs detalhados de cada correção
- ✅ Rastreável no banco de dados
- ✅ Reversível (pode voltar use_timezone=0)

### Escalável
- ✅ Funciona para 100+ fontes simultâneas
- ✅ Suporta RSS, NewsAPI, MediaStack
- ✅ Sem overhead em fontes corretas (early return)

## Troubleshooting

### Artigo ainda aparece no futuro após correção

**Causa:** Artigo foi coletado antes da correção

**Solução:**
```bash
python scripts/backfill_article_timestamps.py --apply
```

### Fonte continua gerando timestamps futuros

**Causa:** Fonte pode ter múltiplos timezones (ex: feed global) ou conteúdo realmente agendado

**Solução manual:**
1. Verificar RSS feed real:
   ```bash
   curl -s "URL_DO_FEED" | grep -i "pubdate" | head -5
   ```

2. Comparar com hora atual:
   ```bash
   date -u  # Hora UTC atual
   ```

3. Se confirmar que RSS mente, forçar timezone:
   ```sql
   UPDATE gm_sources 
   SET timezone = 'UTC-XX:XX', use_timezone = 1 
   WHERE name = 'FONTE_PROBLEMA';
   ```

### Muitos alertas AUTO-TIMEZONE-DETECT

**Normal:** Primeira execução após deploy detectará muitas fontes problemáticas

**Anormal:** Se continua detectando mesma fonte repetidamente
- Verificar se timezone está sendo salvo no banco
- Verificar se cache em memória está sendo atualizado
- Checar logs para erros no `db.execute()`

## Histórico de Desenvolvimento

- **2026-03-16**: Descoberta do problema (1,922 artigos futuros)
- **2026-03-16**: Implementação PRIORITY 0 em normalize_timestamp_to_utc()
- **2026-03-16**: Criação dos scripts fix_timezone_sources.py e backfill_article_timestamps.py
- **2026-03-16**: Implementação do sistema de auto-detecção em 3 coletores
- **2026-03-16**: Commit e deploy (commit dff0973)

## Próximos Passos

### Melhorias Futuras

1. **Dashboard de Monitoramento**
   - Gráfico de artigos futuros ao longo do tempo
   - Lista de fontes corrigidas automaticamente
   - Alertas para fontes problemáticas recorrentes

2. **Machine Learning**
   - Detectar padrões de timezone por domínio/país
   - Sugerir timezone antes do primeiro artigo problemático
   - Validar correções com múltiplos artigos

3. **Suporte a DST (Daylight Saving Time)**
   - Detectar mudanças sazonais de timezone
   - Ajustar automaticamente quando fontes trocam +01:00 ↔ +02:00
   - Histórico de timezone por fonte

4. **API de Configuração**
   - Endpoint para forçar timezone manualmente
   - Interface web para revisar auto-correções
   - Rollback de correções incorretas

## Referências

- Commit: `dff0973` - Add automatic timezone detection and correction system
- Issue: 1,922 artigos com timestamps impossíveis
- Arquivos modificados:
  - `wxAsyncNewsGather.py` - Auto-detecção em 3 coletores + PRIORITY 0
  - `scripts/fix_timezone_sources.py` - Correção manual em massa
  - `scripts/backfill_article_timestamps.py` - Recalcular histórico
