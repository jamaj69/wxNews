# wxAsyncNewsReader - Compatibility Fixes

## 🐛 Problems Found

### 1. Missing API Keys Error
```
decouple.UndefinedValueError: NEWS_API_KEY_3 not found. 
Declare it as envvar or define a default value.
```

### 2. SQLAlchemy 2.0 Compatibility Error
```
sqlalchemy.exc.ArgumentError: expected schema argument to be a string, 
got <class 'sqlalchemy.engine.base.Engine'>.
```

## ✅ Solutions Applied

### Fix 1: Removed Unused API Keys
Removed unused API key declarations from wxAsyncNewsReader.py.

### What Changed
The reader was trying to load 4 API keys but only using 1:
- ❌ Removed: `API_KEY2`, `API_KEY3`, `API_KEY4` (never used)
- ✅ Kept: `API_KEY1` (used in `getNewsSources()`)

**Before:**
```python
API_KEY1 = config('NEWS_API_KEY_1')
API_KEY2 = config('NEWS_API_KEY_2')
API_KEY3 = config('NEWS_API_KEY_3')  # ❌ Not in .env
API_KEY4 = config('NEWS_API_KEY_4')  # ❌ Not in .env
```

**After:**
```python
# Only API_KEY1 is used by the reader (for getNewsSources)
API_KEY1 = config('NEWS_API_KEY_1')
```

### Fix 2: Updated SQLAlchemy Syntax for 2.0+

Your system has **SQLAlchemy 2.0.46** which deprecated old syntax patterns.

#### Change 1: MetaData initialization
**Before:**
```python
self.meta = MetaData(self.eng)  # ❌ Deprecated in 2.0
```

**After:**
```python
self.meta = MetaData()  # ✅ Correct for 2.0+
```

#### Change 2: Table autoload
**Before:**
```python
self.gm_sources = Table('gm_sources', self.meta, autoload=True)  # ❌ Deprecated
```

**After:**
```python
self.gm_sources = Table('gm_sources', self.meta, autoload_with=self.eng)  # ✅ Correct
```

#### Change 3: select() statements
**Before:**
```python
stm = select([gm_sources])  # ❌ List deprecated in 2.0
stm1 = select([gm_articles]).where(...)  # ❌ List deprecated
```

**After:**
```python
stm = select(gm_sources)  # ✅ Correct for 2.0+
stm1 = select(gm_articles).where(...)  # ✅ Correct
```

## 📋 Component API Key Usage

| Component | API Keys Used | Purpose |
|-----------|---------------|---------|
| **wxAsyncNewsReader.py** | `NEWS_API_KEY_1` only | Get list of available sources |
| **wxAsyncNewsGather.py** | `NEWS_API_KEY_1`, `NEWS_API_KEY_2` | Collect news (EN/ES with KEY_1, PT/IT with KEY_2) |

## 🚀 Ready to Run

The reader is now fixed and ready to use:

```bash
# Start the reader
python wxAsyncNewsReader.py

# Or use the helper script
./start_news_reader.sh
```

## ✔️ Verification

All checks passed:
- ✅ Syntax validation: OK
- ✅ SQLAlchemy version: 2.0.46 detected
- ✅ All deprecated syntax updated
- ✅ Required modules: Available (wx, wxasync, sqlalchemy, decouple)
- ✅ API key in .env: Present (`NEWS_API_KEY_1`)
- ✅ Database connection: Tested successfully
- ✅ Database content: 9.8 MB with sources and articles

### Database Test Results
```
✅ Database connection OK - Found source: Ars Technica
✅ Articles table OK - Found article: Fact check: Trump makes false claims...
```

## 📝 Notes

- The reader **only displays** news from the database
- The reader **does not collect** news (that's the Collector's job)
- The reader only needs `NEWS_API_KEY_1` to populate the sources list
- All actual news content comes from the database, populated by wxAsyncNewsGather.py

## 🎯 Next Steps

1. **Start the Collector** (if not already running):
   ```bash
   ./start_news_collector.sh
   ```

2. **Wait ~30 seconds** for initial news collection

3. **Start the Reader**:
   ```bash
   ./start_news_reader.sh
   ```

4. **Browse your news!**

The system should now work flawlessly. The reader will display news sources and articles collected by wxAsyncNewsGather.py.
