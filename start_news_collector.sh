#!/bin/bash
# start_news_collector.sh - Start the news collection service in background

cd "$(dirname "$0")"

echo "Starting News Collector..."
echo "Log file: collector.log"
echo ""

python wxAsyncNewsGather.py > collector.log 2>&1 &
COLLECTOR_PID=$!

echo "✅ News Collector started (PID: $COLLECTOR_PID)"
echo ""
echo "To monitor logs:"
echo "  tail -f collector.log"
echo ""
echo "To stop collector:"
echo "  kill $COLLECTOR_PID"
echo "  OR: pkill -f wxAsyncNewsGather"
echo ""
echo "To start the reader GUI:"
echo "  python wxAsyncNewsReader.py"
echo ""

# Save PID to file
echo $COLLECTOR_PID > collector.pid
echo "PID saved to collector.pid"
