#!/usr/bin/env python3
"""
Clean article titles in the database by normalizing whitespace.

This script:
1. Finds all articles with extra whitespace in titles (double spaces, leading/trailing spaces)
2. Normalizes the whitespace
3. Updates the database

Run this once to clean existing data.
"""

import os
import sqlite3
from pathlib import Path

def clean_title(title):
    """Normalize whitespace in a title string."""
    if not title:
        return title
    # Collapse multiple whitespace into single spaces and strip
    return ' '.join(title.split())

def main():
    # Database path
    db_path = Path(__file__).parent / 'predator_news.db'
    
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return
    
    print(f"📊 Opening database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all articles with their current titles
    print("🔍 Analyzing titles...")
    cursor.execute("SELECT id_article, title FROM gm_articles WHERE title IS NOT NULL")
    articles = cursor.fetchall()
    
    print(f"📈 Found {len(articles)} articles with titles")
    
    # Check which titles need cleaning
    titles_to_clean = []
    for article_id, title in articles:
        cleaned_title = clean_title(title)
        if title != cleaned_title:
            titles_to_clean.append((cleaned_title, article_id, title))
    
    if not titles_to_clean:
        print("✅ All titles are already clean! No updates needed.")
        conn.close()
        return
    
    print(f"🧹 Found {len(titles_to_clean)} titles that need cleaning")
    print("\nExamples of titles to clean:")
    for cleaned, article_id, original in titles_to_clean[:5]:
        print(f"  Before: {repr(original[:60])}")
        print(f"  After:  {repr(cleaned[:60])}")
        print()
    
    # Ask for confirmation
    response = input(f"\n⚠️  Update {len(titles_to_clean)} titles? [y/N]: ")
    if response.lower() != 'y':
        print("❌ Cancelled. No changes made.")
        conn.close()
        return
    
    # Update the titles
    print("\n🔄 Updating titles...")
    updated = 0
    for cleaned_title, article_id, original_title in titles_to_clean:
        try:
            cursor.execute(
                "UPDATE gm_articles SET title = ? WHERE id_article = ?",
                (cleaned_title, article_id)
            )
            updated += 1
            if updated % 100 == 0:
                print(f"  Progress: {updated}/{len(titles_to_clean)}")
        except Exception as e:
            print(f"  ⚠️  Failed to update article {article_id}: {e}")
    
    # Commit changes
    conn.commit()
    print(f"\n✅ Successfully updated {updated} titles")
    
    # Verify
    cursor.execute("""
        SELECT COUNT(*) FROM gm_articles 
        WHERE title LIKE '%  %' OR title LIKE ' %' OR title LIKE '% '
    """)
    remaining = cursor.fetchone()[0]
    
    if remaining > 0:
        print(f"⚠️  Warning: {remaining} titles still have whitespace issues")
    else:
        print("✅ All titles are now clean!")
    
    conn.close()

if __name__ == '__main__':
    main()
