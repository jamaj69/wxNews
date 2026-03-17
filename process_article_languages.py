#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch process existing articles to detect language and optionally translate
"""

import asyncio
import sqlite3
import os
import sys
import logging
from typing import List, Dict, Optional
from datetime import datetime
from decouple import config

# Add parent directory to path to import language_service
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_service import LanguageService, TranslationBackend

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_path():
    """Get database path from environment"""
    db_path = str(config('DB_PATH', default='predator_news.db', cast=str))
    if not os.path.isabs(db_path):
        # Get project root directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # If we're in a subdirectory, go up to project root
        if os.path.basename(script_dir) in ['scripts', 'utils']:
            project_root = os.path.dirname(script_dir)
        else:
            project_root = script_dir
        db_path = os.path.join(project_root, db_path)
    return db_path


class ArticleLanguageProcessor:
    """Process articles for language detection and translation"""
    
    def __init__(self, 
                 target_language: str = 'pt',
                 enable_translation: bool = True,
                 translate_content: bool = False,
                 batch_size: int = 100,
                 rate_limit_delay: float = 0.1):
        """
        Initialize processor
        
        Args:
            target_language: Target language for translation
            enable_translation: Whether to translate articles
            translate_content: Whether to translate full article content (slower)
            batch_size: Number of articles to process per batch
            rate_limit_delay: Delay between translations (seconds) to avoid rate limiting
        """
        self.db_path = get_db_path()
        self.target_language = target_language
        self.enable_translation = enable_translation
        self.translate_content = translate_content
        self.batch_size = batch_size
        self.rate_limit_delay = rate_limit_delay
        
        self.language_service = LanguageService(
            translation_backend=TranslationBackend.GOOGLETRANS,
            target_language=target_language,
            enable_translation=enable_translation
        )
        
        self.stats = {
            'total': 0,
            'processed': 0,
            'detected': 0,
            'translated': 0,
            'skipped': 0,
            'errors': 0,
            'languages': {}
        }
    
    def get_articles_to_process(self, 
                               limit: Optional[int] = None,
                               unprocessed_only: bool = True) -> List[Dict]:
        """
        Get articles that need language processing
        
        Args:
            limit: Maximum number of articles to fetch
            unprocessed_only: Only get articles without detected language
            
        Returns:
            List of article dictionaries
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Build query
        query = """
            SELECT 
                id_article, title, description, content,
                detected_language, language_confidence
            FROM gm_articles
        """
        
        if unprocessed_only:
            query += " WHERE detected_language IS NULL"
        
        query += " ORDER BY inserted_at_ms DESC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        articles = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        logger.info(f"📊 Found {len(articles)} articles to process")
        return articles
    
    async def process_article(self, article: Dict) -> Optional[Dict]:
        """
        Process a single article: detect language and optionally translate
        
        Returns:
            Dict with processing results or None if failed
        """
        try:
            # Process article
            result = await self.language_service.process_article(
                title=article['title'] or '',
                description=article['description'],
                content=article['content'],
                translate_content=self.translate_content
            )
            
            # Update stats
            if result['detected_language'] != 'unknown':
                self.stats['detected'] += 1
                lang = result['detected_language']
                self.stats['languages'][lang] = self.stats['languages'].get(lang, 0) + 1
            
            if result['translated_title']:
                self.stats['translated'] += 1
            
            self.stats['processed'] += 1
            
            return {
                'id_article': article['id_article'],
                'detected_language': result['detected_language'],
                'language_confidence': result['confidence'],
                'translated_title': result['translated_title'],
                'translated_description': result['translated_description'],
                'translated_content': result['translated_content']
            }
            
        except Exception as e:
            logger.error(f"Error processing article {article['id_article']}: {e}")
            self.stats['errors'] += 1
            return None
    
    async def process_batch(self, articles: List[Dict]) -> List[Dict]:
        """Process a batch of articles"""
        tasks = [self.process_article(article) for article in articles]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None and exceptions
        valid_results = [r for r in results if r and not isinstance(r, Exception)]
        
        # Add small delay to avoid rate limiting
        if self.enable_translation and valid_results:
            await asyncio.sleep(self.rate_limit_delay * len(valid_results))
        
        return valid_results
    
    def update_articles(self, results: List[Dict]):
        """Update articles in database with language detection results"""
        if not results:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            for result in results:
                cursor.execute("""
                    UPDATE gm_articles
                    SET detected_language = ?,
                        language_confidence = ?,
                        translated_title = ?,
                        translated_description = ?,
                        translated_content = ?
                    WHERE id_article = ?
                """, (
                    result['detected_language'],
                    result['language_confidence'],
                    result['translated_title'],
                    result['translated_description'],
                    result['translated_content'],
                    result['id_article']
                ))
            
            conn.commit()
            logger.info(f"✅ Updated {len(results)} articles in database")
            
        except Exception as e:
            logger.error(f"Database update error: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    async def process_all(self, limit: Optional[int] = None):
        """Process all articles in batches"""
        logger.info("="*70)
        logger.info("ARTICLE LANGUAGE DETECTION & TRANSLATION")
        logger.info("="*70)
        logger.info(f"Target language: {self.target_language}")
        logger.info(f"Translation enabled: {self.enable_translation}")
        logger.info(f"Translate content: {self.translate_content}")
        logger.info(f"Batch size: {self.batch_size}")
        logger.info("")
        
        # Get articles
        articles = self.get_articles_to_process(limit=limit, unprocessed_only=True)
        self.stats['total'] = len(articles)
        
        if not articles:
            logger.info("✅ No articles to process!")
            return
        
        # Process in batches
        start_time = datetime.now()
        
        for i in range(0, len(articles), self.batch_size):
            batch = articles[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (len(articles) + self.batch_size - 1) // self.batch_size
            
            logger.info(f"🔄 Processing batch {batch_num}/{total_batches} ({len(batch)} articles)...")
            
            results = await self.process_batch(batch)
            
            # Update database
            if results:
                self.update_articles(results)
            
            # Show progress
            progress = (i + len(batch)) / len(articles) * 100
            logger.info(f"   Progress: {progress:.1f}% ({i + len(batch)}/{len(articles)})")
        
        # Final stats
        elapsed = (datetime.now() - start_time).total_seconds()
        
        logger.info("")
        logger.info("="*70)
        logger.info("PROCESSING COMPLETE")
        logger.info("="*70)
        logger.info(f"Total articles: {self.stats['total']:,}")
        logger.info(f"Processed: {self.stats['processed']:,}")
        logger.info(f"Detected: {self.stats['detected']:,}")
        logger.info(f"Translated: {self.stats['translated']:,}")
        logger.info(f"Errors: {self.stats['errors']:,}")
        logger.info(f"Time: {elapsed:.1f}s ({self.stats['processed']/elapsed:.1f} articles/sec)")
        
        logger.info("")
        logger.info("Languages detected:")
        for lang, count in sorted(self.stats['languages'].items(), key=lambda x: x[1], reverse=True):
            percentage = count / self.stats['detected'] * 100
            logger.info(f"  {lang}: {count:,} ({percentage:.1f}%)")


async def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Detect language and translate articles')
    parser.add_argument('--limit', type=int, help='Limit number of articles to process')
    parser.add_argument('--target-lang', default='pt', help='Target language for translation (default: pt)')
    parser.add_argument('--no-translate', action='store_true', help='Only detect language, do not translate')
    parser.add_argument('--translate-content', action='store_true', help='Also translate full article content (slower)')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size (default: 50)')
    parser.add_argument('--rate-limit', type=float, default=0.1, help='Delay between translations in seconds (default: 0.1)')
    
    args = parser.parse_args()
    
    processor = ArticleLanguageProcessor(
        target_language=args.target_lang,
        enable_translation=not args.no_translate,
        translate_content=args.translate_content,
        batch_size=args.batch_size,
        rate_limit_delay=args.rate_limit
    )
    
    await processor.process_all(limit=args.limit)


if __name__ == '__main__':
    asyncio.run(main())
