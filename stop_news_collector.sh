#!/bin/bash
# stop_news_collector.sh - Stop the news collection service

cd "$(dirname "$0")"

if [ -f collector.pid ]; then
    PID=$(cat collector.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "Stopping News Collector (PID: $PID)..."
        kill $PID
        echo "✅ Collector stopped"
        rm collector.pid
    else
        echo "⚠️  Process $PID not found (already stopped?)"
        rm collector.pid
    fi
else
    echo "⚠️  No collector.pid file found"
    echo "Attempting to stop by name..."
    pkill -f wxAsyncNewsGather && echo "✅ Collector stopped" || echo "❌ No collector process found"
fi
