# Article Content Enrichment

## Overview

The news gatherer now automatically fetches missing content from article URLs when RSS feeds only provide title and link information. This significantly improves the reading experience for sources like Haaretz that don't include full article content in their RSS feeds.

## How It Works

### Automatic Enrichment During Collection

When the news gatherer processes an article from RSS, NewsAPI, or MediaStack:

1. **Checks for missing data**: If author, description, or content is empty
2. **Fetches the article webpage**: Downloads HTML from the article URL
3. **Extracts metadata**: Using multiple extraction strategies:
   - **Author**: From meta tags, bylines, structured data (Schema.org)
   - **Publication time**: From meta tags, `<time>` elements
   - **Description**: From Open Graph tags, meta descriptions
   - **Content**: First 3-5 paragraphs from article body
4. **Updates article before saving**: Enriched data is stored in database

### Extraction Strategies

The content fetcher uses multiple fallback strategies:

```
Meta Tags → Structured Data → CSS Classes → Fallback Parsing
```

- **Meta tags**: `article:author`, `og:description`, `article:published_time`
- **Structured data**: Schema.org markup (itemprop attributes)
- **CSS classes**: Common patterns like `article-content`, `author-name`, `byline`
- **Fallback**: Finds all `<p>` tags and filters by content length

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Enable/disable content enrichment
ENRICH_MISSING_CONTENT=true

# Timeout for fetching content (seconds)
ENRICH_TIMEOUT=10
```

### Default Behavior

- **Enabled by default**: `ENRICH_MISSING_CONTENT=true`
- **10 second timeout**: Prevents slow requests from blocking collection
- **Only for missing data**: If article already has author/description/content, enrichment is skipped
- **Non-blocking**: Runs in thread pool to avoid blocking async collection loop

## Performance Considerations

### Impact on Collection Speed

- Each enrichment adds ~2-5 seconds per article (depending on site response time)
- Only affects articles with missing content (~70-85% of RSS articles)
- Runs in parallel with other collection tasks

### Optimization Tips

1. **Reduce timeout** if your internet is fast:
   ```bash
   ENRICH_TIMEOUT=5
   ```

2. **Disable for faster collection** (if you don't need content):
   ```bash
   ENRICH_MISSING_CONTENT=false
   ```

3. **Monitor logs** to see which sources need enrichment:
   ```
   ✅ [Haaretz] Enriched article with: author, description, content
   ⚠️  [TechCrunch] Fetch succeeded but no new data found
   ```

## Limitations

### What It Can't Fetch

1. **Paywalled content**: Sites requiring login/subscription
2. **JavaScript-rendered content**: Single Page Apps (SPAs) that load content dynamically
3. **Bot-protected sites**: Sites using Cloudflare, reCAPTCHA, etc.
4. **Geo-restricted content**: Sites blocking access from certain regions

### Error Handling

When content fetching fails:
- **No crash**: Error is logged, article still saved with original data
- **Fallback**: Original RSS data is preserved
- **Log messages**:
  ```
  ⚠️  [Source] Content fetch failed or returned no data
  ⚠️  [Source] Error fetching content: Connection timeout
  ```

## Examples

### Before Enrichment
```json
{
  "title": "Except on the other side of the fence",
  "author": "",
  "description": "",
  "content": "",
  "url": "https://www.haaretz.com/..."
}
```

### After Enrichment
```json
{
  "title": "Except on the other side of the fence",
  "author": "Carolina Landsmann",
  "description": "Opinion: The Arab community's democratic threat to the right",
  "content": "First paragraph... Second paragraph... Third paragraph...",
  "url": "https://www.haaretz.com/..."
}
```

## Manual Fetching (Reader UI)

The article detail viewer also has a **"🔄 Fetch Missing Content"** button for manually fetching content on-demand. This is useful for:

- Articles collected before enrichment was enabled
- Articles where automatic enrichment failed
- Re-attempting after network issues

## Logs

Watch the gatherer logs for enrichment activity:

```bash
# During collection
🔍 [Haaretz] Attempting to fetch missing content from URL...
✅ [Haaretz] Enriched article with: author, description, content

# Statistics in reader
Source: Haaretz (45 articles, 38 enriched)
```

## Statistics

Based on current database:
- **Total articles**: 13,273
- **Articles with empty content**: 10,251 (77%)
- **Potential for enrichment**: Very high for RSS sources
- **Success rate**: Varies by source (30-80%)

## Troubleshooting

### Enrichment Not Working

1. **Check configuration**:
   ```bash
   grep ENRICH .env
   ```

2. **Check logs**:
   ```bash
   tail -f pytweeter.log | grep -i enrich
   ```

3. **Test specific URL**:
   ```bash
   python3 article_fetcher.py "https://example.com/article"
   ```

### Site-Specific Issues

Some sites may require custom extractors. Contact maintainer to add support for specific news sources.

## Future Enhancements

- [ ] Cache extracted content to reduce re-fetching
- [ ] Support for JavaScript-rendered sites (Playwright/Selenium)
- [ ] Per-source enrichment strategies
- [ ] Parallel batch enrichment for backfilling old articles
- [ ] Machine learning-based content extraction

## Related Files

- `article_fetcher.py`: Core content extraction logic
- `wxAsyncNewsGather.py`: Integration with news collection
- `wxAsyncNewsReader.py`: Manual fetch button in UI
- `.env.example`: Configuration template
