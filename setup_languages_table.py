#!/usr/bin/env python3
"""
Setup languages table for translation management
Creates a table to track supported languages and translation preferences
"""

import sqlite3
import os
from decouple import config


def get_db_path():
    """Get database path from config"""
    db_path = str(config('DB_PATH', default='predator_news.db'))
    if not os.path.isabs(db_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, db_path)
    return db_path


def setup_languages_table():
    """Create and populate languages table"""
    
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("🌍 Setting up languages table...\n")
    
    # Create languages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS languages (
            language_code TEXT PRIMARY KEY,
            language_name TEXT NOT NULL,
            native_name TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            use_translation INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    print("✅ Table 'languages' created")
    
    # Common languages with their native names
    # is_default: 1 for Portuguese (our default language)
    # use_translation: 1 for languages that should be translated to Portuguese
    languages_data = [
        # (code, english_name, native_name, is_default, use_translation)
        ('pt', 'Portuguese', 'Português', 1, 0),  # Default language - no translation needed
        ('pt-BR', 'Portuguese (Brazil)', 'Português (Brasil)', 1, 0),  # Also default
        ('en', 'English', 'English', 0, 1),  # Translate to Portuguese
        ('es', 'Spanish', 'Español', 0, 1),  # Translate to Portuguese
        ('fr', 'French', 'Français', 0, 1),
        ('de', 'German', 'Deutsch', 0, 1),
        ('it', 'Italian', 'Italiano', 0, 1),
        ('ru', 'Russian', 'Русский', 0, 1),
        ('ja', 'Japanese', '日本語', 0, 1),
        ('zh', 'Chinese', '中文', 0, 1),
        ('ar', 'Arabic', 'العربية', 0, 1),
        ('hi', 'Hindi', 'हिन्दी', 0, 1),
        ('ko', 'Korean', '한국어', 0, 1),
        ('nl', 'Dutch', 'Nederlands', 0, 1),
        ('pl', 'Polish', 'Polski', 0, 1),
        ('sv', 'Swedish', 'Svenska', 0, 1),
        ('tr', 'Turkish', 'Türkçe', 0, 1),
        ('fa', 'Persian', 'فارسی', 0, 1),  # Detected in database
        ('he', 'Hebrew', 'עברית', 0, 1),
        ('uk', 'Ukrainian', 'Українська', 0, 1),
        ('vi', 'Vietnamese', 'Tiếng Việt', 0, 1),
        ('id', 'Indonesian', 'Bahasa Indonesia', 0, 1),
        ('th', 'Thai', 'ไทย', 0, 1),
        ('cs', 'Czech', 'Čeština', 0, 1),
        ('ro', 'Romanian', 'Română', 0, 1),
        ('el', 'Greek', 'Ελληνικά', 0, 1),
        ('da', 'Danish', 'Dansk', 0, 1),
        ('fi', 'Finnish', 'Suomi', 0, 1),
        ('no', 'Norwegian', 'Norsk', 0, 1),
        ('bg', 'Bulgarian', 'Български', 0, 1),
        ('hr', 'Croatian', 'Hrvatski', 0, 1),
        ('sk', 'Slovak', 'Slovenčina', 0, 1),
    ]
    
    # Insert languages (ignore if already exists)
    inserted = 0
    updated = 0
    
    for lang_code, eng_name, native_name, is_default, use_translation in languages_data:
        try:
            # Check if exists
            cursor.execute("SELECT language_code FROM languages WHERE language_code = ?", (lang_code,))
            if cursor.fetchone():
                # Update existing
                cursor.execute("""
                    UPDATE languages 
                    SET language_name = ?, native_name = ?, is_default = ?, 
                        use_translation = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE language_code = ?
                """, (eng_name, native_name, is_default, use_translation, lang_code))
                updated += 1
            else:
                # Insert new
                cursor.execute("""
                    INSERT INTO languages (language_code, language_name, native_name, is_default, use_translation)
                    VALUES (?, ?, ?, ?, ?)
                """, (lang_code, eng_name, native_name, is_default, use_translation))
                inserted += 1
        except Exception as e:
            print(f"⚠️  Error with language {lang_code}: {e}")
    
    conn.commit()
    
    print(f"✅ Inserted {inserted} new languages")
    print(f"✅ Updated {updated} existing languages")
    
    # Get languages detected in articles but not in our table
    cursor.execute("""
        SELECT DISTINCT detected_language, COUNT(*) as count
        FROM gm_articles 
        WHERE detected_language IS NOT NULL 
          AND detected_language NOT IN (SELECT language_code FROM languages)
        GROUP BY detected_language
        ORDER BY count DESC
    """)
    
    missing_langs = cursor.fetchall()
    if missing_langs:
        print(f"\n⚠️  Found {len(missing_langs)} language(s) in articles not in languages table:")
        for lang, count in missing_langs:
            print(f"   - {lang}: {count} articles")
            # Add with default settings
            cursor.execute("""
                INSERT OR IGNORE INTO languages (language_code, language_name, native_name, is_default, use_translation)
                VALUES (?, ?, ?, 0, 1)
            """, (lang, f'Unknown ({lang})', f'Unknown ({lang})'))
        conn.commit()
        print("   (Added to table with use_translation=1)")
    
    # Show summary
    print("\n📊 Languages Summary:")
    cursor.execute("""
        SELECT 
            language_code,
            language_name,
            native_name,
            is_default,
            use_translation,
            (SELECT COUNT(*) FROM gm_articles WHERE detected_language = languages.language_code) as article_count
        FROM languages
        ORDER BY is_default DESC, article_count DESC, language_name
    """)
    
    print("\n{:<10} {:<20} {:<20} {:<10} {:<15} {:<10}".format(
        "Code", "Language", "Native Name", "Default", "Translate", "Articles"
    ))
    print("-" * 95)
    
    for row in cursor.fetchall():
        code, eng, native, is_def, use_trans, count = row
        default_mark = "✓" if is_def else ""
        trans_mark = "✓" if use_trans else ""
        print("{:<10} {:<20} {:<20} {:<10} {:<15} {:<10}".format(
            code, eng[:20], native[:20], default_mark, trans_mark, count or 0
        ))
    
    # Show statistics
    cursor.execute("SELECT COUNT(*) FROM languages")
    total_langs = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM languages WHERE is_default = 1")
    default_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM languages WHERE use_translation = 1")
    translate_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM gm_articles WHERE detected_language IS NOT NULL")
    articles_with_lang = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM gm_articles")
    total_articles = cursor.fetchone()[0]
    
    print("\n" + "=" * 95)
    print(f"Total languages in table: {total_langs}")
    print(f"Default language(s): {default_count}")
    print(f"Languages set for translation: {translate_count}")
    print(f"Articles with detected language: {articles_with_lang:,} / {total_articles:,}")
    print("=" * 95)
    
    conn.close()
    print("\n✅ Languages table setup complete!")


def list_languages(filter_type=None):
    """List languages with optional filter"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = "SELECT language_code, language_name, native_name, is_default, use_translation FROM languages"
    
    if filter_type == 'default':
        query += " WHERE is_default = 1"
    elif filter_type == 'translate':
        query += " WHERE use_translation = 1"
    
    query += " ORDER BY language_name"
    
    cursor.execute(query)
    return cursor.fetchall()


def update_language_translation(language_code, use_translation):
    """Update translation flag for a language"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE languages 
        SET use_translation = ?, updated_at = CURRENT_TIMESTAMP
        WHERE language_code = ?
    """, (use_translation, language_code))
    
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    
    return affected > 0


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Setup and manage languages table',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Setup/update languages table:
  python setup_languages_table.py
  
  # List all languages:
  python setup_languages_table.py --list
  
  # List only languages marked for translation:
  python setup_languages_table.py --list-translate
  
  # Enable translation for a language:
  python setup_languages_table.py --enable-translation en
  
  # Disable translation for a language:
  python setup_languages_table.py --disable-translation en
        """
    )
    
    parser.add_argument('--list', action='store_true', help='List all languages')
    parser.add_argument('--list-default', action='store_true', help='List default languages')
    parser.add_argument('--list-translate', action='store_true', help='List languages marked for translation')
    parser.add_argument('--enable-translation', metavar='CODE', help='Enable translation for language code')
    parser.add_argument('--disable-translation', metavar='CODE', help='Disable translation for language code')
    
    args = parser.parse_args()
    
    if args.list or args.list_default or args.list_translate:
        filter_type = 'default' if args.list_default else ('translate' if args.list_translate else None)
        langs = list_languages(filter_type)
        
        print("\n{:<10} {:<25} {:<25} {:<10} {:<15}".format(
            "Code", "Language", "Native Name", "Default", "Translate"
        ))
        print("-" * 90)
        
        for code, eng, native, is_def, use_trans in langs:
            default_mark = "✓" if is_def else ""
            trans_mark = "✓" if use_trans else ""
            print("{:<10} {:<25} {:<25} {:<10} {:<15}".format(
                code, eng, native, default_mark, trans_mark
            ))
        print()
        
    elif args.enable_translation:
        if update_language_translation(args.enable_translation, 1):
            print(f"✅ Translation enabled for language: {args.enable_translation}")
        else:
            print(f"❌ Language not found: {args.enable_translation}")
            
    elif args.disable_translation:
        if update_language_translation(args.disable_translation, 0):
            print(f"✅ Translation disabled for language: {args.disable_translation}")
        else:
            print(f"❌ Language not found: {args.disable_translation}")
            
    else:
        # Default: setup table
        setup_languages_table()


if __name__ == '__main__':
    main()
