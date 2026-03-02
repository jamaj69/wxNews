# Article Content Backfill Guide

## Overview

The `backfill_article_content.py` script enriches existing articles in the database by fetching missing content from their URLs.

**Current Status:**
- Total articles in database: ~13,273
- Articles with empty content: ~10,251 (77%)
- **These can be enriched!**

## Quick Start

### 1. Test with Dry Run (Recommended First Step)

```bash
# Test with 10 articles to see what will happen
python3 backfill_article_content.py --limit 10 --dry-run
```

This will:
- Show which articles will be processed
- Attempt to fetch content
- **NOT update the database**
- Show success/failure results

### 2. Run Small Batch

```bash
# Process 100 articles for real
python3 backfill_article_content.py --limit 100 --delay 1
```

### 3. Run Full Backfill

⚠️ **WARNING**: This will take several hours (~3-8 hours for 10,000 articles)

```bash
# Process ALL articles with missing content
python3 backfill_article_content.py --delay 0.5
```

## Command Options

| Option | Description | Default | Example |
|--------|-------------|---------|---------|
| `--limit N` | Process only N articles | All | `--limit 100` |
| `--dry-run` | Don't update database | False | `--dry-run` |
| `--source ID` | Process specific source only | All | `--source rss-haaretz` |
| `--timeout N` | Fetch timeout (seconds) | 10 | `--timeout 15` |
| `--batch N` | Progress report interval | 100 | `--batch 50` |
| `--delay N` | Delay between fetches (sec) | 1.0 | `--delay 0.5` |

## Usage Examples

### Enrich Haaretz Articles Only

```bash
python3 backfill_article_content.py --source rss-www-haaretz-com --delay 2
```

### Fast Processing (More Aggressive)

```bash
python3 backfill_article_content.py --delay 0.2 --timeout 5
```

### Conservative (Slower, More Reliable)

```bash
python3 backfill_article_content.py --delay 2 --timeout 15
```

### Test Specific Amount

```bash
# Test with 50 articles
python3 backfill_article_content.py --limit 50 --delay 1
```

## Expected Results

Based on testing:
- **Success rate**: 30-60% (varies by source)
- **Speed**: 0.3-1.0 articles/second (with delays)
- **Time for all**: ~3-8 hours for 10,000 articles

### What Gets Enriched

✅ **Often successful:**
- Major news sites (CNN, BBC, ESPN, etc.)
- Sites with good SEO metadata
- Sites without paywalls

⚠️ **Sometimes fails:**
- Paywalled content (Politico, some newspapers)
- JavaScript-heavy sites
- Sites with bot protection

❌ **Never works:**
- Sites requiring login
- Geo-restricted content
- Sites blocking all automated access

## Monitoring Progress

### Watch Live Progress

Open another terminal and run:

```bash
# Watch the log file
tail -f backfill.log | grep -E "✅|❌|Progress"
```

### Check Statistics

The script shows progress every batch:

```
Progress: 100/10251 (0%)
  Enriched: 42, Failed: 58
  Rate: 0.5 articles/sec, ETA: 5.7 hours
  Fields: author=38, desc=25, content=31
```

## Safety Features

### Data Preservation

✅ **Original RSS data is NEVER overwritten**
- Only empty fields are filled
- Existing data is always preserved
- If fetch fails, article remains unchanged

### Interruption Handling

- Press `Ctrl+C` to stop at any time
- Already processed articles are saved
- You can run the script again - it will only process articles that still need enrichment
- Use `--limit` to resume in smaller batches

### Database Safety

- Uses transactions for each update
- Commits after every successful enrichment
- No risk of data corruption
- 30-second timeout prevents database locks

## Performance Tips

### For Faster Processing

1. **Reduce delay**: `--delay 0.2` (but may trigger rate limits)
2. **Reduce timeout**: `--timeout 5` (but may miss slow sites)
3. **Use VPS/Server**: Better network = faster fetches

### For Better Results

1. **Increase delay**: `--delay 2` (more polite to servers)
2. **Increase timeout**: `--timeout 15` (wait for slow sites)
3. **Process in batches**: Run multiple times with `--limit 1000`

## Troubleshooting

### Script is Too Slow

```bash
# Reduce delay and timeout
python3 backfill_article_content.py --delay 0.3 --timeout 5
```

### Getting Many Failures

```bash
# Increase timeout, be more patient
python3 backfill_article_content.py --delay 2 --timeout 20
```

### Database Locked Error

```bash
# Stop the news gatherer temporarily
pkill -f wxAsyncNewsGather.py

# Run backfill
python3 backfill_article_content.py --limit 1000

# Restart gatherer
python3 wxAsyncNewsGather.py &
```

### Want to See More Details

```bash
# Check the detailed log
tail -f backfill.log
```

## Logs

Two types of logs are created:

1. **Console output**: Progress and summary
2. **backfill.log**: Detailed log of every operation

The log file contains:
- Every fetch attempt
- Success/failure per article
- Error messages
- Final statistics

## After Backfill

### Check Results

```bash
# Count articles with content now
sqlite3 predator_news.db "SELECT COUNT(*) FROM gm_articles WHERE content != '' AND content IS NOT NULL;"
```

### View Improved Articles

Open `wxAsyncNewsReader.py` and browse articles - you should see:
- More author names
- More descriptions
- More article content (first few paragraphs)

### Re-run for Updates

You can run the script again anytime new articles are added:

```bash
# Process newest articles first (they're more likely to succeed)
python3 backfill_article_content.py --limit 500
```

## Recommended Workflow

### First Time

```bash
# 1. Test dry run
python3 backfill_article_content.py --limit 20 --dry-run

# 2. Small real run
python3 backfill_article_content.py --limit 100

# 3. Check results
# Open wxAsyncNewsReader and verify articles look better

# 4. Run larger batch
python3 backfill_article_content.py --limit 1000

# 5. Eventually run full backfill (leave running overnight)
nohup python3 backfill_article_content.py --delay 0.5 > backfill_full.log 2>&1 &
```

### Ongoing Maintenance

```bash
# Run weekly to enrich new articles
python3 backfill_article_content.py --limit 500 --delay 1
```

## Estimated Time & Results

For **10,251 articles** with empty content:

| Delay | Articles/sec | Total Time | Expected Enriched |
|-------|--------------|------------|-------------------|
| 0.2s  | 0.8-1.0      | 3-4 hours  | 3,000-5,000 |
| 0.5s  | 0.5-0.7      | 4-6 hours  | 3,000-5,000 |
| 1.0s  | 0.3-0.5      | 6-9 hours  | 3,000-5,000 |
| 2.0s  | 0.2-0.3      | 10-14 hours| 3,000-5,000 |

**Success rate varies by source:**
- News sites with good SEO: 60-80%
- Paywalled sites: 10-20%
- Overall average: 30-50%

## Questions?

Check the logs: `backfill.log` and `pytweeter.log`
