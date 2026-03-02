# RSS Feed Validation Report

**Test Date**: 2026-02-26  
**Test Duration**: 54.1 seconds  
**Total Feeds Tested**: 157

---

## 📊 Executive Summary

| Status | Count | Percentage |
|--------|-------|------------|
| ✅ **Working** | **114** | **72%** |
| ❌ Broken | 28 | 17% |
| ⚠️ Invalid XML | 14 | 8% |
| ⏱️ Timeout | 1 | 0% |

**Conclusion**: **72% of RSS feeds are still operational** after ~3 years.

---

## ✅ Working Feeds (114 feeds)

### By Domain (Top 15)

| Domain | Feed Count |
|--------|------------|
| www.rfi.fr | 9 feeds |
| feeds.feedburner.com | 8 feeds |
| www.cnbc.com | 8 feeds |
| www.wired.com | 5 feeds |
| www.koreatimes.co.kr | 4 feeds |
| www.haaretz.com | 4 feeds |
| www.handelsblatt.com | 3 feeds |
| feeds.bbci.co.uk | 2 feeds |
| www.nytimes.com | 2 feeds |
| rss.cnn.com | 2 feeds |
| www.spiegel.de | 2 feeds |
| contenidos.lanacion.com.ar | 2 feeds |
| www.popsci.com | 2 feeds |
| www.tagesspiegel.de | 2 feeds |

### Top 10 Fastest (Most Reliable)

| Rank | Response Time | Entries | Domain |
|------|---------------|---------|--------|
| 1 | 0.05s | 45 | www.theguardian.com |
| 2 | 0.05s | 50 | www.euronews.com |
| 3 | 0.05s | 50 | www.wired.com |
| 4 | 0.06s | 44 | finance.yahoo.com |
| 5 | 0.06s | 100 | www.newscientist.com |
| 6 | 0.07s | 5 | businessday.ng |
| 7 | 0.10s | 31 | feeds.bbci.co.uk |
| 8 | 0.11s | 10 | www.npr.org |
| 9 | 0.12s | 20 | www.wired.com |
| 10 | 0.13s | 50 | www.buzzfeed.com |

### Most Content-Rich Feeds

| Rank | Entries | Source | Domain |
|------|---------|--------|--------|
| 1 | 200 | news18.com India News | www.news18.com |
| 2 | 100 | The Hindu Business Line | www.thehindubusinessline.com |
| 3 | 100 | RT World News | www.rt.com |
| 4 | 100 | The Independent World | www.independent.co.uk |
| 5 | 100 | TIME | time.com |
| 6 | 100 | LA NACION (Argentina) | contenidos.lanacion.com.ar |
| 7 | 100 | g1 (Brazil) | g1.globo.com |
| 8 | 100 | New Scientist | www.newscientist.com |
| 9 | 100 | The Hindu | www.thehindu.com |
| 10 | 59 | Tagesspiegel (Germany) | www.tagesspiegel.de |

---

## ❌ Broken/Problematic Feeds (43 feeds)

### By Error Type

| Error Type | Count | Severity |
|------------|-------|----------|
| HTTP 403 Forbidden | 12 | 🔴 High |
| HTTP 404 Not Found | 11 | 🔴 High |
| Malformed XML | 8 | 🟡 Medium |
| Empty Feed | 5 | 🟡 Medium |
| Connection/SSL Error | 3 | 🔴 High |
| HTTP 410 Gone | 2 | 🔴 High |
| Timeout | 1 | 🟡 Medium |

### HTTP 403 Forbidden (12 feeds) - Access Denied

These sites are blocking automated requests:
- www.yahoo.com (2 feeds)
- defence-blog.com
- www.business-standard.com
- mjbizdaily.com
- www.bmmagazine.co.uk
- www.aljazeera.com
- www.rawstory.com
- www.seattletimes.com
- www.thecipherbrief.com
- economictimes.indiatimes.com
- www.moneyweb.co.za

### HTTP 404 Not Found (11 feeds) - Page Removed

These feeds no longer exist:
- www.e-ir.info
- worldnewssuperfast.blogspot.com
- bbj.hu
- www.abc.net.au
- www.ctvnews.ca
- www.channelnewsasia.com
- www.thehindubusinessline.com
- www.cbsnews.com
- www.ft.com
- uk.news.yahoo.com
- feeds.breakingnews.ie

### HTTP 410 Gone (2 feeds) - Permanently Removed

- www.financialexpress.com
- www.sciencemag.org

### Malformed XML (8 feeds)

Invalid RSS/XML structure:
- www.koreaherald.com (4 feeds - all broken)
- br.noticias.yahoo.com
- it.notizie.yahoo.com
- sputniknews.com
- mothership.sg

### Empty Feeds (5 feeds)

Valid XML but no content:
- www.birminghampost.co.uk
- www.vox.com
- www.dailytelegraph.com.au
- oglobo.globo.com
- www.jpost.com

### Connection/SSL Errors (3 feeds)

Cannot establish connection:
- www.biztrailblazer.com (DNS failure)
- www.revyuh.com (SSL handshake failure)
- www.businessinsider.sg (TLS alert)

### Timeout (1 feed)

Too slow to respond:
- feeds.washingtonpost.com

---

## 📁 Generated Files

1. **rssfeeds_working.conf** (114 feeds)
   - Contains only working RSS feeds
   - Ready to use in production
   - 72% of original feeds

2. **rss_feed_test_results.json**
   - Complete test results in JSON format
   - Includes response times, entry counts, errors
   - Useful for further analysis

3. **broken_rss_urls.txt**
   - List of all broken URLs by category
   - 43 broken feeds documented

4. **RSS_VALIDATION_REPORT.md** (this file)
   - Human-readable summary

---

## 🔧 Recommendations

### 1. **Use Working Feeds File**
Replace `rssfeeds.conf` with `rssfeeds_working.conf`:
```bash
cp rssfeeds.conf rssfeeds.conf.backup
cp rssfeeds_working.conf rssfeeds.conf
```

### 2. **Fix HTTP 403 Issues**
Add user agent rotation or use proxy for:
- yahoo.com feeds (2 feeds affected)
- defence-blog.com
- business-standard.com

### 3. **Find Replacements**
Replace permanently gone feeds (HTTP 410, 404):
- Financial Express → Alternative Indian business news
- Science Magazine → Alternative science sources
- Breaking News Ireland → Irish Times RSS

### 4. **Remove Dead Feeds**
Delete from configuration:
- All 4 koreaherald.com feeds (malformed XML)
- blogspot.com feeds (404)
- SSL error domains

### 5. **Monitor Slow Feeds**
Consider removing or increasing timeout for:
- feeds.washingtonpost.com (timeout)
- www.tagesspiegel.de (2.6s response)
- www.handelsblatt.com (2.3s response)

---

## 📈 Performance Analysis

### Response Time Distribution

| Time Range | Count | Percentage |
|------------|-------|------------|
| < 0.5s | 68 | 59% |
| 0.5s - 1.0s | 32 | 28% |
| 1.0s - 2.0s | 11 | 9% |
| > 2.0s | 3 | 2% |

### Content Distribution

| Entry Count | Feed Count |
|-------------|------------|
| 1-20 entries | 52 feeds |
| 21-50 entries | 41 feeds |
| 51-100 entries | 20 feeds |
| 100+ entries | 1 feed |

---

## 🎯 Next Steps

1. ✅ **Replace config file** with working feeds only
2. ⚠️ **Find alternatives** for high-value broken feeds (Al Jazeera, Washington Post)
3. 🔄 **Re-test monthly** to catch newly broken feeds
4. 📊 **Monitor** performance and remove consistently slow feeds
5. 🆕 **Add new feeds** to replace broken ones

---

## 🏆 Best Performing Feeds

**Most Reliable + Fast + Content-Rich:**

1. **New Scientist** - 0.06s, 100 entries
2. **The Guardian** - 0.05s, 45 entries
3. **BBC News** - 0.10s, 31 entries
4. **CNN** - Various feeds, consistent performance
5. **Wired** - 0.05-0.20s, 20-50 entries per feed
6. **RFI** - 9 working feeds, 0.13-0.71s
7. **CNBC** - 8 working feeds, business/finance focus

**Recommendation**: Prioritize these sources in your collection strategy.

---

**Report Generated**: 2026-02-26  
**Tool**: test_rss_feeds.py  
**Status**: ✅ Complete
