#!/bin/bash
# Quick start script for wxAsyncNewsGather with FastAPI
# Use this for manual testing or development

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║    Starting wxAsyncNewsGather with FastAPI (Development)       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check dependencies
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "❌ FastAPI not installed"
    echo "   Install with: pip install -r requirements-fastapi.txt"
    exit 1
fi

if ! python3 -c "import uvicorn" 2>/dev/null; then
    echo "❌ Uvicorn not installed"
    echo "   Install with: pip install -r requirements-fastapi.txt"
    exit 1
fi

# Check database
if [ ! -f "predator_news.db" ]; then
    echo "⚠️  Database not found: predator_news.db"
    echo "   The service will create it on first run"
    echo ""
fi

echo "🚀 Starting server..."
echo ""

# Start the server
python3 wxAsyncNewsGatherAPI.py

# This won't be reached unless the server is stopped
echo ""
echo "🛑 Server stopped"
