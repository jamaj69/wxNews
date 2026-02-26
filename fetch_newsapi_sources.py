#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NewsAPI Sources by Category
Fetch and organize news sources by topic: technology, AI, science, politics, economics, etc.

Created: 2026-02-26
"""

import requests
import json
from decouple import config
from datetime import datetime

# Load API keys
API_KEY1 = config('NEWS_API_KEY_1')
API_KEY2 = config('NEWS_API_KEY_2')

# Categories we're interested in
CATEGORIES = ['technology', 'science', 'business', 'general', 'health']
LANGUAGES = ['en', 'pt', 'es', 'it', 'de', 'fr']

def fetch_sources_by_category(api_key):
    """Fetch all available sources from NewsAPI"""
    
    url = f"https://newsapi.org/v2/top-headlines/sources?apiKey={api_key}"
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data['status'] == 'ok':
                return data['sources']
            else:
                print(f"❌ API Error: {data.get('message', 'Unknown error')}")
                return []
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return []


def organize_sources_by_category(sources):
    """Organize sources by category and language"""
    
    organized = {
        'technology': [],
        'science': [],
        'business': [],
        'general': [],
        'health': [],
        'entertainment': [],
        'sports': []
    }
    
    by_language = {}
    
    for source in sources:
        category = source.get('category', 'general')
        language = source.get('language', 'unknown')
        
        # Add to category
        if category in organized:
            organized[category].append(source)
        
        # Add to language
        if language not in by_language:
            by_language[language] = []
        by_language[language].append(source)
    
    return organized, by_language


def filter_relevant_sources(sources):
    """
    Filter sources for tech, AI, science, politics, economics
    """
    
    # Keywords for AI/ML/Tech
    tech_keywords = ['tech', 'technology', 'wired', 'verge', 'ars', 'techcrunch', 
                     'hacker', 'engadget', 'gizmodo', 'mashable']
    
    # Keywords for Science
    science_keywords = ['science', 'scientific', 'nature', 'research', 'medical',
                        'health', 'new scientist']
    
    # Keywords for Business/Economics
    business_keywords = ['business', 'financial', 'economic', 'fortune', 'forbes',
                         'wall street', 'bloomberg', 'economist', 'market']
    
    # Keywords for Politics/News
    politics_keywords = ['politic', 'times', 'post', 'news', 'guardian', 'reuters',
                         'associated press', 'bbc', 'cnn', 'nbc', 'cbs', 'abc']
    
    filtered = {
        'technology_ai': [],
        'science': [],
        'business_economics': [],
        'politics_top_news': [],
        'other': []
    }
    
    for source in sources:
        name_lower = source['name'].lower()
        desc_lower = source.get('description', '').lower()
        category = source.get('category', '')
        combined = f"{name_lower} {desc_lower}"
        
        matched = False
        
        # Check Technology/AI
        if category == 'technology' or any(kw in combined for kw in tech_keywords):
            filtered['technology_ai'].append(source)
            matched = True
        
        # Check Science
        if category == 'science' or any(kw in combined for kw in science_keywords):
            filtered['science'].append(source)
            matched = True
        
        # Check Business/Economics
        if category == 'business' or any(kw in combined for kw in business_keywords):
            filtered['business_economics'].append(source)
            matched = True
        
        # Check Politics/Top News
        if category == 'general' or any(kw in combined for kw in politics_keywords):
            filtered['politics_top_news'].append(source)
            matched = True
        
        if not matched:
            filtered['other'].append(source)
    
    return filtered


def print_sources_report(sources, filtered):
    """Print detailed report"""
    
    print("\n" + "=" * 80)
    print(" NEWSAPI SOURCES REPORT - By Category")
    print("=" * 80)
    print(f"Total sources available: {len(sources)}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    
    # By our filtered categories
    print("-" * 80)
    print("FILTERED BY YOUR INTERESTS:")
    print("-" * 80)
    
    for category, items in filtered.items():
        if category != 'other':
            print(f"\n📰 {category.upper().replace('_', ' ')} ({len(items)} sources)")
            print("-" * 80)
            
            for source in sorted(items, key=lambda x: x['name']):
                lang = source.get('language', '??').upper()
                country = source.get('country', '??').upper()
                cat = source.get('category', 'general')
                print(f"  • {source['name']} [{lang}/{country}] ({cat})")
                print(f"    {source.get('description', 'No description')[:100]}...")
                print(f"    URL: {source.get('url', 'N/A')}")
                print()
    
    # Other sources
    if filtered['other']:
        print(f"\n📋 OTHER CATEGORIES ({len(filtered['other'])} sources)")
        print("-" * 80)
        for source in filtered['other']:
            print(f"  • {source['name']} ({source.get('category', 'unknown')})")
    
    print("\n" + "=" * 80)


def save_sources_json(sources, filtered, filename='newsapi_sources_by_category.json'):
    """Save to JSON file"""
    
    data = {
        'timestamp': datetime.now().isoformat(),
        'total_sources': len(sources),
        'all_sources': sources,
        'filtered': filtered,
        'summary': {
            'technology_ai': len(filtered['technology_ai']),
            'science': len(filtered['science']),
            'business_economics': len(filtered['business_economics']),
            'politics_top_news': len(filtered['politics_top_news']),
            'other': len(filtered['other'])
        }
    }
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Saved to: {filename}")


def create_database_insert_sql(filtered):
    """Generate SQL INSERT statements for filtered sources"""
    
    sql_file = 'newsapi_sources_insert.sql'
    
    with open(sql_file, 'w', encoding='utf-8') as f:
        f.write("-- NewsAPI Sources INSERT statements\n")
        f.write(f"-- Generated: {datetime.now().isoformat()}\n")
        f.write("-- Categories: Technology/AI, Science, Business/Economics, Politics/Top News\n\n")
        
        f.write("BEGIN;\n\n")
        
        for category, sources in filtered.items():
            if category == 'other':
                continue
                
            f.write(f"-- {category.upper().replace('_', ' ')} ({len(sources)} sources)\n")
            
            for source in sources:
                source_id = source['id'] if source['id'] else source['name'].lower().replace(' ', '-')
                name = source['name'].replace("'", "''")
                description = source.get('description', '').replace("'", "''")
                url = source.get('url', '').replace("'", "''")
                cat = source.get('category', 'general')
                lang = source.get('language', 'en')
                country = source.get('country', 'us')
                
                sql = f"""INSERT INTO gm_sources (id_source, name, description, url, category, language, country)
VALUES ('{source_id}', '{name}', '{description}', '{url}', '{cat}', '{lang}', '{country}')
ON CONFLICT (id_source) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    url = EXCLUDED.url,
    category = EXCLUDED.category,
    language = EXCLUDED.language,
    country = EXCLUDED.country;

"""
                f.write(sql)
            
            f.write("\n")
        
        f.write("COMMIT;\n")
    
    print(f"✅ SQL file created: {sql_file}")


if __name__ == '__main__':
    print("=" * 80)
    print(" NEWSAPI SOURCES FETCHER")
    print(" Categories: Technology/AI, Science, Business/Economics, Politics/News")
    print("=" * 80)
    
    # Fetch sources
    print("\n📡 Fetching sources from NewsAPI...")
    sources = fetch_sources_by_category(API_KEY1)
    
    if not sources:
        print("❌ Failed to fetch sources. Check your API key in .env file.")
        exit(1)
    
    print(f"✅ Fetched {len(sources)} total sources")
    
    # Filter by our interests
    print("\n🔍 Filtering by categories...")
    filtered = filter_relevant_sources(sources)
    
    # Print report
    print_sources_report(sources, filtered)
    
    # Summary
    print("\n" + "=" * 80)
    print(" SUMMARY")
    print("=" * 80)
    print(f"  Technology/AI:       {len(filtered['technology_ai'])} sources")
    print(f"  Science:             {len(filtered['science'])} sources")
    print(f"  Business/Economics:  {len(filtered['business_economics'])} sources")
    print(f"  Politics/Top News:   {len(filtered['politics_top_news'])} sources")
    print(f"  Other:               {len(filtered['other'])} sources")
    print("-" * 80)
    
    total_relevant = (len(filtered['technology_ai']) + 
                     len(filtered['science']) + 
                     len(filtered['business_economics']) + 
                     len(filtered['politics_top_news']))
    
    print(f"  TOTAL RELEVANT:      {total_relevant} sources")
    print("=" * 80)
    
    # Save to files
    print("\n💾 Saving results...")
    save_sources_json(sources, filtered)
    create_database_insert_sql(filtered)
    
    print("\n✅ Done!")
    print("\nNext steps:")
    print("  1. Review: cat newsapi_sources_by_category.json")
    print("  2. Import to DB: psql -U predator -d predator3_dev -f newsapi_sources_insert.sql")
    print("  3. Or use: python3 database_recovery_script.py --newsapi")
