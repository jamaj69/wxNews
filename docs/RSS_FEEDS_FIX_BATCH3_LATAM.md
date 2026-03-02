# RSS Feeds - Correção Batch 3: Limpeza Latino-Americana
**Data:** 2026-03-01 16:52

## Contexto
38 feeds de notícias em espanhol e português foram identificados com erros críticos:
- HTTP 404 (feed desativado)
- HTTP 410 (feed permanentemente removido)
- HTTP 403 (bloqueado)
- Invalid content type (retornando HTML em vez de RSS)
- Erros de encoding UTF-8
- Erros de conexão/DNS

## Feeds Deletados (37 feeds)

### Espanhol - Espanha
1. **La Razón** - HTTP 404
2. **La Vanguardia** - HTTP 410
3. **Público España** - HTTP 404

### Espanhol - México
4. **El Universal México** - HTTP 404
5. **Milenio** - HTTP 404
6. **Excélsior** - HTTP 404
7. **Reforma** - Erro UTF-8
8. **El Financiero México** - HTML retornado
9. **El Economista México** - HTTP 403

### Espanhol - Argentina
10. **Página/12** - HTTP 404
11. **Infobae Argentina** - HTTP 404

### Espanhol - Colômbia
12. **El Tiempo Colombia** - HTML retornado
13. **El Espectador** - HTTP 404
14. **Semana** - HTTP 404
15. **Portafolio Colombia** - HTML retornado

### Espanhol - Chile
16. **El Mercurio Chile** - HTML retornado
17. **La Tercera** - HTTP 404
18. **Las Últimas Noticias** - HTTP 404
19. **Emol** - Connection reset

### Espanhol - Peru
20. **El Comercio Perú** - HTTP 404

### Espanhol - Outros Países
21. **El Deber Bolivia** - HTTP 404
22. **El Nuevo Diario Nicaragua** - DNS não resolve
23. **CNN en Español** - HTTP 404
24. **La Nación Costa Rica** - HTTP 404
25. **Listín Diario** (Rep. Dominicana) - HTTP 404
26. **La Prensa Honduras** - HTTP 404
27. **La Prensa Panamá** - HTML retornado
28. **El Observador Uruguay** - HTML retornado
29. **El Nacional Venezuela** - Múltiplos timeouts (já bloqueado automaticamente)
30. **BBC Mundo** - HTTP 404

### Português - Brasil
31. **R7 Notícias** - HTTP 404
32. **Estadão** - HTTP 404
33. **Correio Braziliense** - HTTP 404
34. **Estado de Minas** - HTTP 404
35. **O Dia** - HTTP 404
36. **Zero Hora** - HTML retornado
37. **Época** - HTML retornado

## Feeds Mantidos (1 feed)

✅ **Folha de S.Paulo** - Funcionando perfeitamente
- URL: `https://feeds.folha.uol.com.br/emcimadahora/rss091.xml`
- Status: HTTP 200
- Entradas: 100 artigos
- Formato: RSS válido

## Análise

### Motivos da Desativação
- **Migração para APIs pagas**: Muitos jornais latinos migraram para modelos de subscription/paywall
- **Foco em apps móveis**: Desativação de RSS para forçar uso de aplicativos próprios
- **Mudança de plataforma**: Redesign de sites eliminando suporte a RSS legado

### Taxa de Falha
- **Total testado**: 38 feeds
- **Não funcionais**: 37 (97.4%)
- **Funcionais**: 1 (2.6%)

Esta taxa extremamente alta de falha sugere uma tendência regional:
os principais veículos de mídia latino-americanos descontinuaram
massivamente suporte a RSS entre 2024-2026.

## Resultado
- **Deletados**: 37 feeds
- **Mantidos**: 1 feed (Folha de S.Paulo)
- **Total RSS**: 513 fontes ativas (antes: 550)
- **Status**: Serviço reiniciado (PID 2840105)
- **Verificação**: Zero erros dos feeds deletados nos logs

## Comandos Executados
```sql
DELETE FROM gm_sources WHERE id_source IN (
  'rss-bbc-mundo', 'rss-cnn-en-español', 'rss-correio-braziliense',
  'rss-el-comercio-perú', 'rss-el-deber-bolivia', 'rss-el-economista-méxico',
  'rss-el-espectador', 'rss-el-financiero-méxico', 'rss-el-mercurio-chile',
  'rss-el-nacional-venezuela', 'rss-el-nuevo-diario-nicaragua',
  'rss-el-observador-uruguay', 'rss-el-tiempo-colombia', 'rss-el-universal-méxico',
  'rss-emol', 'rss-estado-de-minas', 'rss-estadão', 'rss-excélsior',
  'rss-infobae-argentina', 'rss-la-nación-costa-rica', 'rss-la-prensa-honduras',
  'rss-la-prensa-panamá', 'rss-la-razón', 'rss-la-tercera', 'rss-la-vanguardia',
  'rss-las-últimas-noticias', 'rss-listín-diario', 'rss-milenio', 'rss-o-dia',
  'rss-portafolio-colombia', 'rss-página-12', 'rss-público-españa',
  'rss-r7-notícias', 'rss-reforma', 'rss-semana', 'rss-zero-hora', 'rss-época'
);
```

## Observações
- MediaStack rate limit (429) é normal e esperado
- Sistema agora coleta sem erros de feeds inexistentes
- Logs limpos após reinício
