#!/bin/bash
# start_news_reader.sh - Start the news reader GUI

cd "$(dirname "$0")"

echo "Starting News Reader GUI..."
echo ""

# Check if collector is running
if pgrep -f wxAsyncNewsGather > /dev/null; then
    echo "✅ News Collector is running"
else
    echo "⚠️  News Collector is NOT running!"
    echo "   Start it with: ./start_news_collector.sh"
    echo ""
fi

python wxAsyncNewsReader.py
