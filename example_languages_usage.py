#!/usr/bin/env python3
"""
Example: Using the languages table to filter and translate articles
"""

import sqlite3
import os
from decouple import config


def get_db_path():
    """Get database path"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path


def get_articles_needing_translation(limit=10):
    """
    Get articles that need translation based on languages table configuration
    
    Returns articles where:
    - detected_language is set
    - language is marked for translation (use_translation=1)
    - article doesn't have translation yet (translated_title IS NULL)
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
        SELECT 
            a.id_article,
            a.title,
            a.description,
            a.detected_language,
            l.language_name,
            l.native_name,
            a.url
        FROM gm_articles a
        INNER JOIN languages l ON a.detected_language = l.language_code
        WHERE l.use_translation = 1
          AND a.detected_language IS NOT NULL
          AND a.translated_title IS NULL
        ORDER BY a.inserted_at_ms DESC
        LIMIT ?
    """
    
    cursor.execute(query, (limit,))
    results = cursor.fetchall()
    conn.close()
    
    return results


def get_articles_by_default_language(limit=10):
    """
    Get articles in the default language (Portuguese)
    These don't need translation
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
        SELECT 
            a.id_article,
            a.title,
            a.description,
            a.detected_language,
            l.language_name
        FROM gm_articles a
        INNER JOIN languages l ON a.detected_language = l.language_code
        WHERE l.is_default = 1
        ORDER BY a.inserted_at_ms DESC
        LIMIT ?
    """
    
    cursor.execute(query, (limit,))
    results = cursor.fetchall()
    conn.close()
    
    return results


def get_translation_statistics():
    """Get statistics about translation coverage"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
        SELECT 
            l.language_code,
            l.language_name,
            l.native_name,
            l.use_translation,
            COUNT(a.id_article) as total_articles,
            COUNT(a.translated_title) as translated_articles,
            COUNT(a.id_article) - COUNT(a.translated_title) as pending_translation,
            ROUND(
                CASE 
                    WHEN COUNT(a.id_article) > 0 
                    THEN (COUNT(a.translated_title) * 100.0 / COUNT(a.id_article))
                    ELSE 0 
                END, 
                2
            ) as percent_translated
        FROM languages l
        LEFT JOIN gm_articles a ON a.detected_language = l.language_code
        WHERE l.use_translation = 1
        GROUP BY l.language_code
        HAVING total_articles > 0
        ORDER BY total_articles DESC
    """
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return results


def check_if_should_translate(language_code):
    """
    Check if articles in a given language should be translated
    Returns tuple: (should_translate, is_default_language)
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT use_translation, is_default 
        FROM languages 
        WHERE language_code = ?
    """, (language_code,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return (bool(result[0]), bool(result[1]))
    else:
        # Language not in table, default behavior: translate if not Portuguese
        return (language_code not in ['pt', 'pt-BR'], False)


def main():
    print("=" * 80)
    print("LANGUAGES TABLE - PRACTICAL EXAMPLES")
    print("=" * 80)
    
    # Example 1: Articles needing translation
    print("\n1️⃣  ARTICLES NEEDING TRANSLATION (top 5):\n")
    articles = get_articles_needing_translation(limit=5)
    
    if articles:
        for article in articles:
            id_article, title, desc, lang_code, lang_name, native, url = article
            print(f"   [{lang_code}] {lang_name} ({native})")
            print(f"   Title: {title[:70]}...")
            print(f"   URL: {url}")
            print()
    else:
        print("   ✅ No articles need translation (all are already translated!)\n")
    
    # Example 2: Articles in default language
    print("\n2️⃣  ARTICLES IN DEFAULT LANGUAGE (Portuguese - top 5):\n")
    pt_articles = get_articles_by_default_language(limit=5)
    
    if pt_articles:
        for article in pt_articles:
            id_article, title, desc, lang_code, lang_name = article
            print(f"   [{lang_code}] {title[:70]}...")
            print()
    else:
        print("   ℹ️  No articles detected in Portuguese yet\n")
    
    # Example 3: Translation statistics
    print("\n3️⃣  TRANSLATION STATISTICS BY LANGUAGE:\n")
    stats = get_translation_statistics()
    
    if stats:
        print(f"   {'Code':<8} {'Language':<20} {'Total':<8} {'Translated':<12} {'Pending':<10} {'Progress':<10}")
        print("   " + "-" * 75)
        for stat in stats:
            code, name, native, use_trans, total, translated, pending, percent = stat
            print(f"   {code:<8} {name:<20} {total:<8} {translated:<12} {pending:<10} {percent:>6}%")
        print()
    else:
        print("   ℹ️  No translation statistics available\n")
    
    # Example 4: Check specific languages
    print("\n4️⃣  LANGUAGE TRANSLATION CHECK:\n")
    test_languages = ['en', 'pt', 'es', 'fr', 'pt-BR']
    
    for lang in test_languages:
        should_translate, is_default = check_if_should_translate(lang)
        status = "DEFAULT" if is_default else ("TRANSLATE" if should_translate else "NO TRANSLATE")
        icon = "🏠" if is_default else ("🌐" if should_translate else "⏸️")
        print(f"   {icon} {lang}: {status}")
    
    print("\n" + "=" * 80)


if __name__ == '__main__':
    main()
