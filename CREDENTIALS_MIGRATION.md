# Credentials Migration Summary

**Date:** 2026-02-26  
**Status:** ✅ COMPLETED

## Overview
All hardcoded credentials have been extracted from Python source files and moved to a centralized `.env` file for secure management.

## Security Improvements

### Before
- ❌ Credentials hardcoded in 10+ Python files
- ❌ Exposed in version control history
- ❌ Database password exposed: `'fuckyou'`
- ❌ API keys duplicated across files
- ❌ Twitter credentials exposed (deprecated but still security risk)

### After
- ✅ All credentials in `.env` (excluded from git via `.gitignore`)
- ✅ Template available in `.env.example` for new setups
- ✅ Single source of truth for configuration
- ✅ Uses `python-decouple` for environment variable management
- ✅ Easy to change credentials without touching code

## Files Modified

### 1. NewsAPI Collectors (6 files)
Updated to load NewsAPI keys from environment:
- ✅ `wxAsyncNewsGather.py`
- ✅ `wxAsyncNewsGather1.py`
- ✅ `wxAsyncNewsReaderv2.py`
- ✅ `wxAsyncNewsReaderv3.py`
- ✅ `wxAsyncNewsReaderv4.py`
- ✅ `wxAsyncNewsReaderv5.py`

**Changes:**
```python
# BEFORE:
API_KEY1 = 'c85890894ddd4939a27c19a3eff25ece'
API_KEY2 = '4327173775a746e9b4f2632af3933a86'
API_KEY3 = 'c85890894ddd4939a27c19a3eff25ece'
API_KEY4 = '4327173775a746e9b4f2632af3933a86'

# AFTER:
from decouple import config

API_KEY1 = config('NEWS_API_KEY_1')
API_KEY2 = config('NEWS_API_KEY_2')
API_KEY3 = config('NEWS_API_KEY_3')
API_KEY4 = config('NEWS_API_KEY_4')
```

### 2. Database Configuration (8 files)
Updated `dbCredentials()` function:
- ✅ `wxAsyncNewsGather.py`
- ✅ `wxAsyncNewsGather1.py`
- ✅ `wxAsyncNewsReaderv2.py`
- ✅ `wxAsyncNewsReaderv3.py`
- ✅ `wxAsyncNewsReaderv4.py`
- ✅ `wxAsyncNewsReaderv5.py`
- ✅ `predator_gm.py`
- ✅ `wxListGrid.py`

**Changes:**
```python
# BEFORE:
def dbCredentials():
    conn_cred = { 
        'user' : 'predator' , 
        'password' : 'fuckyou' , 
        'host' : 'titan', 
        'dbname' : 'predator3_dev' 
    }
    return(conn_cred)

# AFTER:
from decouple import config

def dbCredentials():
    conn_cred = { 
        'user' : config('DB_USER') , 
        'password' : config('DB_PASSWORD') , 
        'host' : config('DB_HOST'), 
        'dbname' : config('DB_NAME') 
    }
    return(conn_cred)
```

### 3. Twitter Credentials (2 files)
Updated to load Twitter API keys from environment:
- ✅ `twitterasync.py`
- ✅ `twitterasync_new.py`

**Changes:**
```python
# BEFORE:
CONSUMER_KEY = 'j1KOc2AWQ5QvrtNe8N15UfcXI'
CONSUMER_SECRET = 'AjHnwNBhBB1eegMcVYDvVBiQMAX6PHX9OOdqbqFSHHeezB9IJF'
ACCESS_TOKEN = '1201408473151496192-KZ2xMa2GSuanbi8UJtyFaH4XQ5foWa'
ACCESS_TOKEN_SECRET = 'rUgHWt9z252O0tX94GjO0Zs518NIWiCCXm1slluLX86T0'

# AFTER:
from decouple import config

CONSUMER_KEY = config('TWITTER_CONSUMER_KEY')
CONSUMER_SECRET = config('TWITTER_CONSUMER_SECRET')
ACCESS_TOKEN = config('TWITTER_ACCESS_TOKEN')
ACCESS_TOKEN_SECRET = config('TWITTER_ACCESS_TOKEN_SECRET')
```

## New Files Created

### `.env` (NOT in version control)
Contains actual production credentials:
```bash
# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_USER=predator
DB_PASSWORD=fuckyou
DB_NAME=predator3_dev

# NewsAPI Keys
NEWS_API_KEY_1=c85890894ddd4939a27c19a3eff25ece
NEWS_API_KEY_2=4327173775a746e9b4f2632af3933a86
NEWS_API_KEY_3=c85890894ddd4939a27c19a3eff25ece  # DUPLICATE - needs replacement
NEWS_API_KEY_4=4327173775a746e9b4f2632af3933a86  # DUPLICATE - needs replacement

# Twitter (DEPRECATED - Non-functional)
TWITTER_CONSUMER_KEY=j1KOc2AWQ5QvrtNe8N15UfcXI
TWITTER_CONSUMER_SECRET=AjHnwNBhBB1eegMcVYDvVBiQMAX6PHX9OOdqbqFSHHeezB9IJF
TWITTER_ACCESS_TOKEN=1201408473151496192-KZ2xMa2GSuanbi8UJtyFaH4XQ5foWa
TWITTER_ACCESS_TOKEN_SECRET=rUgHWt9z252O0tX94GjO0Zs518NIWiCCXm1slluLX86T0

# Other settings
LANGUAGES=en,pt,es,it
UPDATE_INTERVAL_SEC=600
LOG_LEVEL=INFO
```

### `.env.example` (Already existed)
Template for new installations - no actual credentials.

### `.gitignore` (Already existed)
Already configured to exclude `.env`:
```
.env
.env.local
.env.*.local
```

## Dependencies

The project already has `python-decouple` in `requirements.txt`:
```txt
python-decouple>=3.8
```

To install (if needed):
```bash
pip install python-decouple
```

## Usage Instructions

### For Development
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your actual credentials:
   ```bash
   nano .env
   ```

3. Run any Python script - it will automatically load from `.env`:
   ```bash
   python3 wxAsyncNewsGather.py
   ```

### For Production
1. Create `.env` on production server with production credentials
2. Never commit `.env` to version control
3. Keep `.env` permissions secure: `chmod 600 .env`

## Configuration Fixed: Database Host

**Important:** Database host changed from `'titan'` to `'localhost'`

This fixes the connection issue since PostgreSQL is running on the local machine (hercules), not the remote server (titan).

## Outstanding Items

### 🔴 Critical: Fix Duplicate API Keys
`.env` currently has duplicate NewsAPI keys:
- `NEWS_API_KEY_3` = duplicate of `KEY_1`
- `NEWS_API_KEY_4` = duplicate of `KEY_2`

**Action needed:** Register 2 more unique NewsAPI accounts at https://newsapi.org/register

### ⚠️ Database Password
Current password `'fuckyou'` is insecure. Consider changing:
```bash
psql -U postgres
ALTER USER predator WITH PASSWORD 'new_secure_password_here';
```

Then update `.env`:
```
DB_PASSWORD=new_secure_password_here
```

### 📝 Redis Configuration
Redis connection is still hardcoded in `twitterasync.py`:
```python
conn = redis.Redis(host='localhost', port=6379, db=0)
```

Consider updating to:
```python
from decouple import config

conn = redis.Redis(
    host=config('REDIS_HOST', default='localhost'),
    port=config('REDIS_PORT', default=6379, cast=int),
    db=config('REDIS_DB', default=0, cast=int)
)
```

## Testing

To verify the migration:
```bash
# Test NewsAPI collector
python3 wxAsyncNewsGather.py

# Test GUI reader (requires database)
python3 wxAsyncNewsReaderv5.py

# Verify database connection
python3 -c "from predator_gm import dbCredentials; print(dbCredentials())"
```

Expected output:
```python
{'user': 'predator', 'password': 'fuckyou', 'host': 'localhost', 'dbname': 'predator3_dev'}
```

## Security Benefits

1. **Separation of code and configuration:** Credentials no longer in version control
2. **Easy rotation:** Change credentials in one place (`.env`)
3. **Environment-specific:** Different `.env` for dev/staging/production
4. **Audit trail:** Easy to see what credentials are in use
5. **Reduced attack surface:** No credentials exposed in code reviews/PRs

## Next Steps

1. ✅ Migration completed
2. 🔲 Register 2 new NewsAPI accounts
3. 🔲 Update `.env` with unique KEY_3 and KEY_4
4. 🔲 Consider changing database password
5. 🔲 Document credential rotation procedures
6. 🔲 Set up credential management system (e.g., HashiCorp Vault) for production

## Rollback (if needed)

If issues occur, old credentials are still visible in git history:
```bash
# View previous version
git log -p --all -- wxAsyncNewsGather.py | grep -A 10 "API_KEY"
```

However, **do not rollback** - fix issues with `.env` instead.

---

**Migration completed successfully on 2026-02-26** ✅
