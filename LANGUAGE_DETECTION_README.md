# Language Detection & Translation for News Articles

This system automatically detects the language of news articles and optionally translates them to your preferred language using free, affordable translation services.

## 🌍 Features

- **Automatic Language Detection**: Identifies the language of each article (English, Portuguese, Spanish, etc.)
- **Confidence Scoring**: Shows how confident the detection is (0.0 to 1.0)
- **Multiple Translation Backends**: Choose from free services:
  - **googletrans** (recommended): Free Google Translate API
  - **deep-translator**: Multiple free backends in one library
  - **argostranslate**: Fully offline translation (no internet required)
- **Batch Processing**: Process thousands of articles efficiently
- **Database Integration**: Stores detected language and translations
- **Rate Limiting**: Respectful API usage to avoid blocking

## 📦 Installation

### 1. Install Required Packages

```bash
# Install language detection (required)
pip install langdetect

# Install translation service (pick one)
pip install googletrans==4.0.0rc1  # Recommended: easiest and most reliable

# Or use deep-translator (alternative)
# pip install deep-translator

# Or use argostranslate (offline, but large downloads)
# pip install argostranslate
```

### 2. Update Database Schema

Add language columns to the `gm_articles` table:

```bash
python scripts/add_language_fields.py
```

This adds:
- `detected_language`: Language code (en, pt, es, fr, de, etc.)
- `language_confidence`: Detection confidence (0.0 to 1.0)
- `translated_title`: Translated article title
- `translated_description`: Translated description

## 🚀 Usage

### Quick Start: Process All Articles

Detect language and translate to Portuguese (default):

```bash
python process_article_languages.py
```

### Process Limited Number of Articles

```bash
# Process only 100 articles
python process_article_languages.py --limit 100

# Process 500 articles
python process_article_languages.py --limit 500
```

### Language Detection Only (No Translation)

If you just want to detect languages without translating:

```bash
python process_article_languages.py --no-translate
```

### Translate to Different Language

```bash
# Translate to English
python process_article_languages.py --target-lang en

# Translate to Spanish
python process_article_languages.py --target-lang es

# Translate to French
python process_article_languages.py --target-lang fr
```

### Advanced Options

```bash
python process_article_languages.py \
    --limit 1000 \
    --target-lang pt \
    --batch-size 50 \
    --rate-limit 0.2
```

Options:
- `--limit N`: Process only N articles
- `--target-lang CODE`: Target language code (pt, en, es, fr, de, it...)
- `--no-translate`: Only detect language, don't translate
- `--batch-size N`: Process N articles per batch (default: 50)
- `--rate-limit SECONDS`: Delay between translations (default: 0.1)

## 📊 Check Language Statistics

View detected languages in your database:

```bash
python scripts/add_language_fields.py
```

Example output:
```
LANGUAGE STATISTICS
======================================================================
Language   Count      Avg Conf     Min Conf     Max Conf    
----------------------------------------------------------------------
en         45,230     0.9987       0.7234       1.0000
pt         8,456      0.9956       0.6891       1.0000
es         3,789      0.9945       0.7123       0.9999
fr         1,234      0.9923       0.6745       0.9998

📊 Articles with translations: 52,255
```

## 🔍 Query Articles by Language

### SQLite Queries

```sql
-- Count articles by language
SELECT detected_language, COUNT(*) as count
FROM gm_articles
WHERE detected_language IS NOT NULL
GROUP BY detected_language
ORDER BY count DESC;

-- Get English articles only
SELECT title, detected_language, language_confidence
FROM gm_articles
WHERE detected_language = 'en'
ORDER BY inserted_at_ms DESC
LIMIT 20;

-- Get non-English articles that need translation
SELECT title, detected_language, translated_title
FROM gm_articles
WHERE detected_language != 'pt' 
  AND detected_language IS NOT NULL
  AND translated_title IS NOT NULL
LIMIT 10;

-- Articles with low confidence (might need review)
SELECT title, detected_language, language_confidence
FROM gm_articles
WHERE language_confidence < 0.85
ORDER BY language_confidence ASC
LIMIT 10;

-- Count translations
SELECT COUNT(*) as translated_articles
FROM gm_articles
WHERE translated_title IS NOT NULL;
```

## 🔧 Programmatic Usage

### In Your Python Code

```python
from language_service import LanguageService, TranslationBackend

# Initialize service
service = LanguageService(
    translation_backend=TranslationBackend.GOOGLETRANS,
    target_language='pt',
    enable_translation=True
)

# Process an article
result = await service.process_article(
    title="Breaking: NASA discovers water on Mars",
    description="Scientists confirm presence of liquid water",
    content="Full article content here..."
)

print(f"Language: {result['detected_language']}")
print(f"Confidence: {result['confidence']:.2%}")
print(f"Translated: {result['translated_title']}")
```

### Quick Functions

```python
from language_service import detect_article_language, translate_article

# Quick language detection
lang, confidence = await detect_article_language(
    title="Article title",
    content="Article content"
)
print(f"Detected: {lang} ({confidence:.2%})")

# Quick translation
translations = await translate_article(
    title="Breaking news",
    description="Article description",
    source_lang='en',
    target_lang='pt'
)
print(f"Translated title: {translations['title']}")
```

## 💰 Cost Analysis

All services used are **FREE**:

| Service | Cost | Limits | Best For |
|---------|------|--------|----------|
| **langdetect** | Free | Unlimited (offline) | Language detection |
| **googletrans** | Free | ~15k requests/hour | General translation |
| **deep-translator** | Free | Varies by backend | Alternative to googletrans |
| **argostranslate** | Free | Unlimited (offline) | Offline use, privacy |

### Recommended Setup

For most users:
```bash
pip install langdetect googletrans==4.0.0rc1
```

For offline/privacy-focused users:
```bash
pip install langdetect argostranslate
# Download language models:
argospm update
argospm install translate-en_pt  # English to Portuguese
argospm install translate-es_pt  # Spanish to Portuguese
```

## 🎯 Integration with News Reader

The language information can be displayed in your news reader:

1. **Article List**: Show language flag or code next to each article
2. **Article Detail**: Display both original and translated versions
3. **Filter by Language**: Show only articles in specific languages
4. **Translation Toggle**: Switch between original and translated text

Example integration (see `wxAsyncNewsReader.py`):
```python
# In article display
language = article.get('detected_language', 'unknown')
confidence = article.get('language_confidence', 0.0)

# Show language info
print(f"🌐 Language: {language} ({confidence:.0%} confidence)")

# Show translation if available
if article.get('translated_title'):
    print(f"🔄 Translation: {article['translated_title']}")
```

## 🔄 Keeping Articles Updated

To process new articles automatically, add language detection to your collection pipeline:

```python
from language_service import LanguageService

async def process_new_article(article):
    service = LanguageService(target_language='pt')
    
    result = await service.process_article(
        title=article['title'],
        description=article['description'],
        content=article['content']
    )
    
    # Save to database
    article['detected_language'] = result['detected_language']
    article['language_confidence'] = result['confidence']
    article['translated_title'] = result['translated_title']
    article['translated_description'] = result['translated_description']
    
    return article
```

## 📈 Performance

Processing speed depends on:
- **Language detection**: ~1000 articles/second (offline, very fast)
- **Translation**: ~5-10 articles/second (depends on network and rate limits)

For 50,000 articles:
- Detection only: ~50 seconds
- Detection + Translation: ~1-2 hours (with rate limiting)

## ⚠️ Important Notes

1. **Rate Limiting**: Translation services have rate limits. The script includes delays to avoid blocking.
2. **Network Required**: googletrans and deep-translator require internet connection.
3. **Accuracy**: Language detection is very accurate (>99%) for articles with sufficient text.
4. **Translation Quality**: Free services provide good quality but may not be perfect for technical/specialized content.
5. **Privacy**: For sensitive content, use argostranslate (fully offline).

## 🐛 Troubleshooting

### ModuleNotFoundError: langdetect

```bash
pip install langdetect
```

### ModuleNotFoundError: googletrans

```bash
pip install googletrans==4.0.0rc1
```

Note: Use this specific version (4.0.0rc1) as it's the most stable.

### Translation Service Not Working

Try alternative backend:
```python
from language_service import LanguageService, TranslationBackend

service = LanguageService(
    translation_backend=TranslationBackend.DEEP_TRANSLATOR
)
```

### Database Locked Error

The script handles this automatically with retry logic. If persists:
```bash
# Stop news collector first
./stop_news_collector.sh

# Run language processing
python process_article_languages.py

# Restart collector
./start_news_collector.sh
```

## 📚 Supported Languages

Common language codes:
- `en` - English
- `pt` - Portuguese
- `es` - Spanish
- `fr` - French
- `de` - German
- `it` - Italian
- `nl` - Dutch
- `ru` - Russian
- `zh-cn` - Chinese (Simplified)
- `ja` - Japanese
- `ko` - Korean
- `ar` - Arabic

See full list: https://py-googletrans.readthedocs.io/en/latest/#googletrans-languages

## 🎓 Examples

### Example 1: Process All Unprocessed Articles

```bash
# Detect language and translate all articles that don't have language info
python process_article_languages.py
```

### Example 2: Quick Test on 10 Articles

```bash
# Test the system on just 10 articles
python process_article_languages.py --limit 10
```

### Example 3: Language Detection Only

```bash
# Just detect languages without translating (very fast)
python process_article_languages.py --no-translate --limit 1000
```

### Example 4: Translate Everything to English

```bash
# If you prefer reading in English
python process_article_languages.py --target-lang en
```

## 📝 Next Steps

1. ✅ Install dependencies
2. ✅ Update database schema
3. ✅ Process existing articles
4. 🔧 Integrate language info into news reader UI
5. 📊 Add language filter to article view
6. 🌐 Add translation toggle button

For questions or issues, check the code in:
- `language_service.py` - Core detection and translation
- `process_article_languages.py` - Batch processing script
- `scripts/add_language_fields.py` - Database schema updates
