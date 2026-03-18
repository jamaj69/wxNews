# Tabela de Idiomas - Documentação

## 📋 Visão Geral

A tabela `languages` gerencia idiomas detectados nos artigos e controla quais devem ser traduzidos.

## 🗃️ Estrutura da Tabela

```sql
CREATE TABLE languages (
    language_code TEXT PRIMARY KEY,      -- Código ISO 639-1 (ex: 'en', 'pt', 'es')
    language_name TEXT NOT NULL,         -- Nome em inglês (ex: 'English', 'Portuguese')
    native_name TEXT NOT NULL,           -- Nome nativo (ex: 'Português', 'Español')
    is_default INTEGER DEFAULT 0,        -- 1 = idioma padrão (pt/pt-BR), 0 = outros
    use_translation INTEGER DEFAULT 0,   -- 1 = traduzir para português, 0 = não traduzir
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

## 🎯 Flags Importantes

### `is_default` (Idioma Padrão)

- **`1`**: Idioma padrão do sistema (Português)
- **`0`**: Outros idiomas
- **Configuração atual**: `pt` e `pt-BR` ambos marcados como padrão

### `use_translation` (Usar Tradução)

- **`1`**: Artigos neste idioma devem ser traduzidos para português
- **`0`**: Não traduzir (usado para português)
- **Configuração atual**: Todos idiomas exceto `pt` e `pt-BR` estão marcados para tradução

## 🔧 Scripts e Comandos

### Script Principal: `setup_languages_table.py`

```bash
# Criar/atualizar tabela de idiomas
python setup_languages_table.py

# Listar todos os idiomas
python setup_languages_table.py --list

# Listar apenas idiomas padrão
python setup_languages_table.py --list-default

# Listar apenas idiomas marcados para tradução
python setup_languages_table.py --list-translate

# Habilitar tradução para um idioma
python setup_languages_table.py --enable-translation en

# Desabilitar tradução para um idioma
python setup_languages_table.py --disable-translation en
```

## 📊 Queries Úteis

### 1. Ver estatísticas por idioma detectado

```sql
SELECT 
    l.language_code,
    l.language_name,
    l.native_name,
    l.is_default,
    l.use_translation,
    COUNT(a.id_article) as article_count,
    COUNT(a.translated_title) as translated_count
FROM languages l
LEFT JOIN gm_articles a ON a.detected_language = l.language_code
GROUP BY l.language_code
ORDER BY article_count DESC;
```

### 2. Artigos que precisam de tradução

```sql
SELECT 
    a.id_article,
    a.title,
    a.detected_language,
    l.language_name,
    CASE 
        WHEN a.translated_title IS NULL THEN 'Pendente'
        ELSE 'Traduzido'
    END as status
FROM gm_articles a
INNER JOIN languages l ON a.detected_language = l.language_code
WHERE l.use_translation = 1
  AND a.detected_language IS NOT NULL
ORDER BY a.inserted_at_ms DESC
LIMIT 100;
```

### 3. Artigos em inglês não traduzidos

```sql
SELECT 
    title,
    url,
    detected_language,
    inserted_at_ms
FROM gm_articles
WHERE detected_language = 'en'
  AND translated_title IS NULL
ORDER BY inserted_at_ms DESC
LIMIT 50;
```

### 4. Contagem de artigos por idioma e status de tradução

```sql
SELECT 
    l.language_code,
    l.language_name,
    COUNT(a.id_article) as total_articles,
    COUNT(a.translated_title) as translated,
    COUNT(a.id_article) - COUNT(a.translated_title) as pending_translation,
    ROUND(COUNT(a.translated_title) * 100.0 / NULLIF(COUNT(a.id_article), 0), 2) as percent_translated
FROM languages l
LEFT JOIN gm_articles a ON a.detected_language = l.language_code
WHERE l.use_translation = 1
GROUP BY l.language_code
HAVING total_articles > 0
ORDER BY total_articles DESC;
```

### 5. Ver idiomas padrão

```sql
SELECT 
    language_code,
    language_name,
    native_name
FROM languages
WHERE is_default = 1;
```

### 6. Ver idiomas configurados para tradução

```sql
SELECT 
    language_code,
    language_name,
    native_name,
    (SELECT COUNT(*) FROM gm_articles WHERE detected_language = languages.language_code) as article_count
FROM languages
WHERE use_translation = 1
ORDER BY language_name;
```

## 🔄 Atualização de Configurações

### Adicionar novo idioma

```sql
INSERT INTO languages (language_code, language_name, native_name, is_default, use_translation)
VALUES ('ca', 'Catalan', 'Català', 0, 1);
```

### Habilitar tradução para um idioma

```sql
UPDATE languages 
SET use_translation = 1, updated_at = CURRENT_TIMESTAMP
WHERE language_code = 'fr';
```

### Desabilitar tradução para um idioma

```sql
UPDATE languages 
SET use_translation = 0, updated_at = CURRENT_TIMESTAMP
WHERE language_code = 'en';
```

### Definir novo idioma padrão (não recomendado alterar)

```sql
-- Primeiro, remover flag de outros
UPDATE languages SET is_default = 0;

-- Depois, marcar o novo padrão
UPDATE languages 
SET is_default = 1, updated_at = CURRENT_TIMESTAMP
WHERE language_code IN ('pt', 'pt-BR');
```

## 📈 Monitoramento

### Artigos sem idioma detectado

```sql
SELECT COUNT(*) as articles_without_language
FROM gm_articles
WHERE detected_language IS NULL;
```

### Taxa de detecção de idioma

```sql
SELECT 
    COUNT(*) as total_articles,
    SUM(CASE WHEN detected_language IS NOT NULL THEN 1 ELSE 0 END) as with_language,
    ROUND(SUM(CASE WHEN detected_language IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as detection_rate
FROM gm_articles;
```

## 🔗 Integração com Sistema de Tradução

### Selecionar próximos artigos para traduzir

```sql
SELECT 
    a.id_article,
    a.title,
    a.description,
    a.content,
    a.detected_language,
    l.language_name
FROM gm_articles a
INNER JOIN languages l ON a.detected_language = l.language_code
WHERE l.use_translation = 1
  AND a.detected_language IS NOT NULL
  AND a.translated_title IS NULL
ORDER BY a.inserted_at_ms DESC
LIMIT 10;
```

### Marcar artigos como traduzidos

```sql
UPDATE gm_articles
SET 
    translated_title = 'Título traduzido',
    translated_description = 'Descrição traduzida',
    translated_content = 'Conteúdo traduzido'
WHERE id_article = 'ARTICLE_ID_HERE';
```

## 📊 Estatísticas Atuais

```bash
# Ver resumo completo
python setup_languages_table.py
```

**Resultado esperado:**

- Total de idiomas: 32
- Idiomas padrão: 2 (pt, pt-BR)
- Idiomas para tradução: 30
- Artigos com idioma detectado: ~33 / 268,931

## ⚠️ Notas Importantes

1. **Idioma Padrão**: `pt` e `pt-BR` são tratados como equivalentes e não precisam tradução
2. **Auto-detecção**: O sistema pode detectar automaticamente novos idiomas nos artigos
3. **Prioridade**: Artigos em inglês (`en`) devem ter prioridade na tradução por serem os mais comuns
4. **Performance**: Use índices apropriados ao fazer queries com JOIN em tabelas grandes

## 🔄 Manutenção Regular

Execute o script periodicamente para adicionar novos idiomas detectados:

```bash
python setup_languages_table.py
```

O script irá:

- Adicionar idiomas novos encontrados nos artigos
- Manter configurações existentes
- Mostrar estatísticas atualizadas
