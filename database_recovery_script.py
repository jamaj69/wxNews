#!/usr/bin/env python3
"""
Database Recovery Script
Recovers predator3_dev database with 275+ sources (118 NewsAPI + 157 RSS)

Usage:
    python3 database_recovery_script.py --create-db
    python3 database_recovery_script.py --populate-sources
    python3 database_recovery_script.py --verify
    python3 database_recovery_script.py --all  # Run all steps
"""

import json
import base64
import zlib
import sys
import argparse
from urllib.parse import urlparse
from sqlalchemy import create_engine, Table, Column, MetaData, Text, inspect
from sqlalchemy.dialects.postgresql import insert, TIMESTAMP


def url_encode(url):
    """Generate 16-char unique ID from URL"""
    return base64.urlsafe_b64encode(zlib.compress(url.encode('utf-8')))[15:31].decode('utf-8')


def get_connection_string(host='localhost', port=5432):
    """Get database connection string"""
    return f'postgresql://predator:fuckyou@{host}:{port}/predator3_dev'


def create_tables(host='localhost', port=5432):
    """Create gm_sources and gm_articles tables"""
    print("📊 Creating database tables...")
    
    try:
        conn_string = get_connection_string(host, port)
        engine = create_engine(conn_string)
        meta = MetaData()

        # Create gm_sources table
        gm_sources = Table(
            'gm_sources', meta,
            Column('id_source', Text, primary_key=True),
            Column('name', Text),
            Column('description', Text),
            Column('url', Text),
            Column('category', Text),
            Column('language', Text),
            Column('country', Text)
        )

        # Create gm_articles table  
        gm_articles = Table(
            'gm_articles', meta,
            Column('id_article', Text, primary_key=True),
            Column('id_source', Text),
            Column('author', Text),
            Column('title', Text),
            Column('description', Text),
            Column('url', Text, unique=True),
            Column('urlToImage', Text),
            Column('publishedAt', TIMESTAMP),
            Column('content', Text)
        )

        meta.create_all(engine)
        print("✅ Tables created successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        return False


def populate_newsapi_sources(host='localhost', port=5432):
    """Populate NewsAPI sources from recovered JSON file"""
    print("\n📰 Populating NewsAPI sources...")
    
    try:
        # Check if file exists
        try:
            with open('newsapi_sources_recovered.json') as f:
                sources = json.load(f)
        except FileNotFoundError:
            print("❌ File 'newsapi_sources_recovered.json' not found")
            print("   Run the recovery script from DATABASE_RECOVERY.md first")
            return False

        conn_string = get_connection_string(host, port)
        engine = create_engine(conn_string)
        meta = MetaData()
        gm_sources = Table('gm_sources', meta, autoload_with=engine)

        conn = engine.connect()
        inserted = 0
        
        for source in sources:
            try:
                source_id = url_encode(source['url'])
                stmt = insert(gm_sources).values(
                    id_source=source_id,
                    name=source['name'],
                    description=source.get('description', ''),
                    url=source['url'],
                    category=source.get('category', ''),
                    language=source.get('language', ''),
                    country=source.get('country', '')
                ).on_conflict_do_nothing(index_elements=['id_source'])
                
                result = conn.execute(stmt)
                conn.commit()
                inserted += 1
                
            except Exception as e:
                print(f"   ⚠️  Error inserting {source.get('name', 'unknown')}: {e}")
                continue

        print(f"✅ Inserted {inserted} NewsAPI sources (from {len(sources)} total)")
        return True
        
    except Exception as e:
        print(f"❌ Error populating NewsAPI sources: {e}")
        return False


def populate_rss_sources(host='localhost', port=5432):
    """Populate RSS feed sources from rssfeeds.conf"""
    print("\n📡 Populating RSS feed sources...")
    
    try:
        # Check if file exists
        try:
            with open('rssfeeds.conf') as f:
                feeds = json.load(f)
        except FileNotFoundError:
            print("❌ File 'rssfeeds.conf' not found")
            return False

        conn_string = get_connection_string(host, port)
        engine = create_engine(conn_string)
        meta = MetaData()
        gm_sources = Table('gm_sources', meta, autoload_with=engine)

        conn = engine.connect()
        inserted = 0
        
        for feed in feeds:
            try:
                source_id = url_encode(feed['url'])
                
                # Extract source name from URL
                parsed = urlparse(feed['url'])
                name = feed.get('label') or parsed.netloc
                
                # Categorize by URL patterns
                url_lower = feed['url'].lower()
                if any(x in url_lower for x in ['business', 'finance', 'economy', 'cnbc']):
                    category = 'business'
                elif any(x in url_lower for x in ['science', 'tech', 'wired']):
                    category = 'technology'
                elif any(x in url_lower for x in ['sport']):
                    category = 'sports'
                else:
                    category = 'general'
                    
                stmt = insert(gm_sources).values(
                    id_source=source_id,
                    name=name,
                    description='',
                    url=feed['url'],
                    category=category,
                    language='',
                    country=''
                ).on_conflict_do_nothing(index_elements=['id_source'])
                
                result = conn.execute(stmt)
                conn.commit()
                inserted += 1
                
            except Exception as e:
                print(f"   ⚠️  Error inserting {feed.get('url', 'unknown')}: {e}")
                continue

        print(f"✅ Inserted {inserted} RSS sources (from {len(feeds)} total)")
        return True
        
    except Exception as e:
        print(f"❌ Error populating RSS sources: {e}")
        return False


def verify_database(host='localhost', port=5432):
    """Verify database tables and content"""
    print("\n🔍 Verifying database...")
    
    try:
        conn_string = get_connection_string(host, port)
        engine = create_engine(conn_string)
        
        # Check if tables exist
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'gm_sources' not in tables:
            print("❌ Table 'gm_sources' not found")
            return False
            
        if 'gm_articles' not in tables:
            print("❌ Table 'gm_articles' not found")
            return False
            
        print("✅ Both tables exist")
        
        # Count sources
        with engine.connect() as conn:
            result = conn.execute("SELECT COUNT(*) FROM gm_sources")
            count = result.fetchone()[0]
            print(f"✅ Found {count} sources in gm_sources table")
            
            # Show sample sources
            print("\n📋 Sample sources:")
            result = conn.execute("""
                SELECT name, category, language, country 
                FROM gm_sources 
                LIMIT 10
            """)
            for row in result:
                print(f"   - {row[0]:40s} | {row[1]:15s} | {row[2]:5s} | {row[3]:5s}")
            
            # Count by category
            result = conn.execute("""
                SELECT category, COUNT(*) 
                FROM gm_sources 
                GROUP BY category 
                ORDER BY COUNT(*) DESC
            """)
            print("\n📊 Sources by category:")
            for row in result:
                print(f"   {row[0]:20s}: {row[1]:3d}")
                
        return True
        
    except Exception as e:
        print(f"❌ Error verifying database: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Recover predator3_dev database')
    parser.add_argument('--create-db', action='store_true', 
                       help='Create database tables')
    parser.add_argument('--populate-sources', action='store_true',
                       help='Populate sources from recovered files')
    parser.add_argument('--verify', action='store_true',
                       help='Verify database content')
    parser.add_argument('--all', action='store_true',
                       help='Run all steps')
    parser.add_argument('--host', default='localhost',
                       help='PostgreSQL host (default: localhost)')
    parser.add_argument('--port', type=int, default=5432,
                       help='PostgreSQL port (default: 5432)')
    
    args = parser.parse_args()
    
    if not any([args.create_db, args.populate_sources, args.verify, args.all]):
        parser.print_help()
        return
    
    print("=" * 70)
    print("DATABASE RECOVERY SCRIPT")
    print("=" * 70)
    print(f"Host: {args.host}:{args.port}")
    print(f"Database: predator3_dev")
    print("=" * 70)
    
    success = True
    
    if args.all or args.create_db:
        success = create_tables(args.host, args.port) and success
    
    if args.all or args.populate_sources:
        success = populate_newsapi_sources(args.host, args.port) and success
        success = populate_rss_sources(args.host, args.port) and success
    
    if args.all or args.verify:
        success = verify_database(args.host, args.port) and success
    
    print("\n" + "=" * 70)
    if success:
        print("✅ RECOVERY COMPLETED SUCCESSFULLY")
    else:
        print("❌ RECOVERY COMPLETED WITH ERRORS")
    print("=" * 70)


if __name__ == '__main__':
    main()
