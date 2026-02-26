#!/usr/bin/env python3
"""
Import RSS sources from JSON to database
"""

import json
import logging
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.dialects.sqlite import insert

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def import_rss_sources(json_file='rss_sources_multilang.json', db_path='predator_news.db'):
    """Import RSS sources from JSON file to database"""
    
    # Load JSON file
    logger.info(f"Loading RSS sources from {json_file}...")
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    sources = data.get('sources', [])
    logger.info(f"Found {len(sources)} sources in JSON file")
    
    # Group by language
    by_lang = {}
    for source in sources:
        lang = source.get('language', 'unknown')
        by_lang[lang] = by_lang.get(lang, 0) + 1
    
    logger.info("Sources by language:")
    for lang, count in sorted(by_lang.items()):
        logger.info(f"  {lang}: {count}")
    
    # Database connection
    eng = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 30, 'check_same_thread': False}
    )
    
    meta = MetaData()
    sources_table = Table('gm_sources', meta, autoload_with=eng)
    
    # Import sources
    logger.info("\nImporting sources to database...")
    inserted = 0
    skipped = 0
    updated = 0
    
    with eng.connect() as conn:
        for source in sources:
            name = source.get('name', 'Unknown')
            url = source.get('url', '')
            language = source.get('language', 'en')
            country = source.get('country', '')
            category = source.get('category', 'general')
            
            if not url:
                logger.warning(f"⚠️  Skipping {name}: no URL")
                skipped += 1
                continue
            
            # Generate source ID
            source_id = f"rss-{name.lower().replace(' ', '-').replace('/', '-')}"
            source_id = source_id[:50]  # Limit length
            
            # Try to insert
            try:
                ins = insert(sources_table).values(
                    id_source=source_id,
                    name=name,
                    description=f"{name} - {category}",
                    url=url,
                    category=category,
                    language=language,
                    country=country
                )
                
                # On conflict, update URL and other fields
                ins_update = ins.on_conflict_do_update(
                    index_elements=['id_source'],
                    set_=dict(
                        name=ins.excluded.name,
                        url=ins.excluded.url,
                        category=ins.excluded.category,
                        language=ins.excluded.language,
                        country=ins.excluded.country
                    )
                )
                
                result = conn.execute(ins_update)
                conn.commit()
                
                if result.rowcount > 0:
                    # Check if it was insert or update
                    # SQLite doesn't differentiate easily, so we count as inserted
                    inserted += 1
                    logger.debug(f"✅ {source_id}: {name}")
                else:
                    skipped += 1
                    logger.debug(f"⏭️  {source_id}: {name} (already exists)")
                    
            except Exception as e:
                logger.error(f"❌ Error importing {name}: {e}")
                conn.rollback()
                skipped += 1
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("📊 IMPORT SUMMARY")
    logger.info(f"  Total sources in JSON: {len(sources)}")
    logger.info(f"  Inserted/Updated: {inserted}")
    logger.info(f"  Skipped: {skipped}")
    logger.info("=" * 80)
    
    # Verify database
    with eng.connect() as conn:
        from sqlalchemy import select, func
        
        # Total RSS sources
        stmt = select(func.count()).select_from(sources_table).where(
            sources_table.c.id_source.like('rss-%')
        )
        total_rss = conn.execute(stmt).scalar()
        
        # By language
        stmt = select(
            sources_table.c.language,
            func.count()
        ).where(
            sources_table.c.id_source.like('rss-%')
        ).group_by(sources_table.c.language)
        
        by_lang_db = dict(conn.execute(stmt).fetchall())
    
    logger.info("\n📊 DATABASE STATS (RSS Sources)")
    logger.info(f"  Total RSS sources: {total_rss}")
    logger.info("  By language:")
    for lang, count in sorted(by_lang_db.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"    {lang}: {count}")


if __name__ == '__main__':
    import sys
    
    json_file = sys.argv[1] if len(sys.argv) > 1 else 'rss_sources_multilang.json'
    import_rss_sources(json_file)
