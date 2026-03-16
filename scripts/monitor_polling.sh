#!/bin/bash
# Monitor wxNewsReader logs for real-time updates
# Usage: ./monitor_polling.sh

echo "============================================================"
echo "  Monitoring wxNewsReader Real-Time Polling"
echo "============================================================"
echo ""
echo "📊 Current Status:"
echo ""

# Check API
echo "1. API Server:"
API_STATUS=$(curl -s http://localhost:8765/api/health 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "   ✅ API is responding"
    echo "   $(echo $API_STATUS | python3 -m json.tool 2>/dev/null | grep -E '(status|collector_running)' | head -2)"
else
    echo "   ❌ API not available"
fi
echo ""

# Check log file
echo "2. wxNewsReader Log:"
if [ -f /tmp/wxnewsreader.log ]; then
    echo "   ✅ Log file exists"
    echo "   Last few lines:"
    tail -5 /tmp/wxnewsreader.log | sed 's/^/      /'
else
    echo "   ⚠️  Log file not found"
fi
echo ""

# Check for recent test articles
echo "3. Recent Test Articles:"
sqlite3 predator_news.db "
    SELECT title, datetime(inserted_at_ms/1000, 'unixepoch', 'localtime') as inserted
    FROM gm_articles 
    WHERE title LIKE '%TEST: Real-Time%'
    ORDER BY inserted_at_ms DESC 
    LIMIT 5
" | while read line; do
    echo "   • $line"
done
echo ""

echo "============================================================"
echo ""
echo "📝 Instructions:"
echo "   1. Make sure wxNewsReader window is open"
echo "   2. Select some news sources on the left"
echo "   3. Click '📰 Load Checked' button"
echo "   4. Wait for next poll (30 seconds)"
echo "   5. Watch for notification toast and new articles"
echo ""
echo "🧪 To insert more test articles:"
echo "   python3 test_realtime_insertion.py 3"
echo ""
echo "📊 To monitor in real-time:"
echo "   tail -f /tmp/wxnewsreader.log | grep -E 'Inserting|Poll|API'"
echo ""
