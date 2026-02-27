# Tests Directory

This directory contains test scripts for the pyTweeter news aggregation system.

## Test Files

### Collection Tests
- `test_news_collection.py` - Test NewsAPI collection
- `test_rss_collection.py` - Test RSS feed collection
- `test_rss_feeds.py` - Test individual RSS feeds
- `test_rss_by_language.py` - Test RSS feeds by language
- `test_complete_collection.py` - End-to-end collection test
- `test_mediastack_integration.py` - Test MediaStack API integration
- `test_mediastack_urls.py` - Test MediaStack URL handling

### Feature Tests
- `test_fetch_article.py` - Test article content fetching from URLs
- `test_tech_blogs.py` - Test technology blog sources

### Integration Tests
- `test_twitter_credentials.py` - Test Twitter/X API credentials (deprecated)

### UI Tests
- `test_reader_quick.py` - Quick test for wxAsyncNewsReader

## Running Tests

Most test scripts can be run directly:

```bash
python3 tests/test_news_collection.py
python3 tests/test_rss_collection.py
python3 tests/test_fetch_article.py [url]
```

## Note

These are primarily standalone test scripts rather than a formal unit test suite. They serve as integration tests and utilities for debugging specific components.

For a proper test suite with pytest, consider organizing these into proper test classes with fixtures and assertions.
