#!/usr/bin/env python3
"""
Test MediaStack integration in wxAsyncNewsGather
"""

import asyncio
import logging
from wxAsyncNewsGather import NewsGather

# Configure logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_mediastack_integration():
    """Test MediaStack collection in the integrated system"""
    print("="*80)
    print("🧪 Testing MediaStack Integration in wxAsyncNewsGather")
    print("="*80)
    
    # Create event loop
    loop = asyncio.get_event_loop()
    
    # Initialize NewsGather
    print("\n📋 Initializing NewsGather...")
    news_gather = NewsGather(loop)
    
    # Test MediaStack collection directly
    print("\n🌍 Testing MediaStack collection...")
    await news_gather.collect_mediastack()
    
    print("\n" + "="*80)
    print("✅ Test complete!")
    print("="*80)

if __name__ == '__main__':
    asyncio.run(test_mediastack_integration())
