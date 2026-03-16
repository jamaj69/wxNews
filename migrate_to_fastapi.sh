#!/bin/bash
# Migration script from Flask to FastAPI version
# This script safely migrates from the old system to the new unified FastAPI system

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     wxAsyncNewsGather Migration to FastAPI                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if running as root for systemd operations
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  This script needs sudo access for systemd operations"
    echo "   You may be prompted for your password"
    echo ""
fi

# Step 1: Check current services
echo "Step 1: Checking current services..."
echo "─────────────────────────────────────"

OLD_GATHER_RUNNING=false
OLD_API_RUNNING=false

if systemctl is-active --quiet wxAsyncNewsGather.service 2>/dev/null; then
    echo "   • wxAsyncNewsGather.service is RUNNING"
    OLD_GATHER_RUNNING=true
else
    echo "   • wxAsyncNewsGather.service is not running"
fi

if systemctl is-active --quiet wxNewsAPI.service 2>/dev/null; then
    echo "   • wxNewsAPI.service is RUNNING"
    OLD_API_RUNNING=true
else
    echo "   • wxNewsAPI.service is not running"
fi

echo ""

# Step 2: Install dependencies
echo "Step 2: Installing FastAPI dependencies..."
echo "─────────────────────────────────────"

if [ -f "requirements-fastapi.txt" ]; then
    pip install -r requirements-fastapi.txt
    echo "   ✅ Dependencies installed"
else
    echo "   ⚠️  requirements-fastapi.txt not found"
    echo "   Installing manually..."
    pip install fastapi uvicorn[standard] pydantic fastapi-cors aiohttp sqlalchemy python-decouple
    echo "   ✅ Dependencies installed"
fi

echo ""

# Step 3: Check database
echo "Step 3: Checking database..."
echo "─────────────────────────────────────"

if [ -f "predator_news.db" ]; then
    # Check if inserted_at_ms column exists
    if sqlite3 predator_news.db "PRAGMA table_info(gm_articles)" | grep -q "inserted_at_ms"; then
        echo "   ✅ Database has inserted_at_ms column"
    else
        echo "   ⚠️  Database missing inserted_at_ms column"
        echo "   Running migration..."
        python3 add_inserted_timestamp.py
        echo "   ✅ Migration completed"
    fi
else
    echo "   ⚠️  Database not found: predator_news.db"
    echo "   The service will create it on first run"
fi

echo ""

# Step 4: Stop old services
if [ "$OLD_GATHER_RUNNING" = true ] || [ "$OLD_API_RUNNING" = true ]; then
    echo "Step 4: Stopping old services..."
    echo "─────────────────────────────────────"
    
    if [ "$OLD_GATHER_RUNNING" = true ]; then
        echo "   Stopping wxAsyncNewsGather.service..."
        sudo systemctl stop wxAsyncNewsGather.service
        echo "   ✅ Stopped wxAsyncNewsGather.service"
    fi
    
    if [ "$OLD_API_RUNNING" = true ]; then
        echo "   Stopping wxNewsAPI.service..."
        sudo systemctl stop wxNewsAPI.service
        echo "   ✅ Stopped wxNewsAPI.service"
    fi
    
    echo ""
fi

# Step 5: Install new service
echo "Step 5: Installing new FastAPI service..."
echo "─────────────────────────────────────"

if [ -f "wxAsyncNewsGatherAPI.service" ]; then
    sudo cp wxAsyncNewsGatherAPI.service /etc/systemd/system/
    sudo systemctl daemon-reload
    echo "   ✅ Service file installed"
else
    echo "   ❌ wxAsyncNewsGatherAPI.service not found"
    exit 1
fi

# Ask if user wants to enable and start service
echo ""
read -p "Do you want to enable and start the new service now? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Enable service
    sudo systemctl enable wxAsyncNewsGatherAPI.service
    echo "   ✅ Service enabled (will start on boot)"
    
    # Start service
    sudo systemctl start wxAsyncNewsGatherAPI.service
    echo "   ✅ Service started"
    
    # Check status
    sleep 2
    echo ""
    echo "Service status:"
    echo "─────────────────────────────────────"
    sudo systemctl status wxAsyncNewsGatherAPI.service --no-pager -l
    
    echo ""
    echo "Testing API..."
    echo "─────────────────────────────────────"
    
    # Wait for service to be ready
    sleep 3
    
    # Test health endpoint
    if curl -f -s http://localhost:8765/api/health > /dev/null 2>&1; then
        echo "   ✅ API is responding"
        echo ""
        echo "API endpoints available at:"
        echo "   • http://localhost:8765/docs (Interactive documentation)"
        echo "   • http://localhost:8765/api/health"
        echo "   • http://localhost:8765/api/articles"
        echo "   • http://localhost:8765/api/stats"
    else
        echo "   ⚠️  API not responding yet (may still be starting up)"
        echo "   Check logs with: sudo journalctl -u wxAsyncNewsGatherAPI.service -f"
    fi
else
    echo "   Service installed but not started"
    echo "   To start manually, run:"
    echo "   sudo systemctl enable --now wxAsyncNewsGatherAPI.service"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    Migration Complete!                         ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║                                                                 ║"
echo "║  New unified service: wxAsyncNewsGatherAPI.service             ║"
echo "║                                                                 ║"
echo "║  Useful commands:                                               ║"
echo "║    • Start:   sudo systemctl start wxAsyncNewsGatherAPI        ║"
echo "║    • Stop:    sudo systemctl stop wxAsyncNewsGatherAPI         ║"
echo "║    • Status:  sudo systemctl status wxAsyncNewsGatherAPI       ║"
echo "║    • Logs:    sudo journalctl -u wxAsyncNewsGatherAPI -f      ║"
echo "║                                                                 ║"
echo "║  Test the API:                                                  ║"
echo "║    python3 test_fastapi_news.py                                ║"
echo "║                                                                 ║"
echo "║  Documentation:                                                 ║"
echo "║    • README: FASTAPI_DOCUMENTATION.md                          ║"
echo "║    • API Docs: http://localhost:8765/docs                      ║"
echo "║                                                                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Optional: Disable old services
if [ "$OLD_GATHER_RUNNING" = true ] || [ "$OLD_API_RUNNING" = true ]; then
    echo ""
    read -p "Do you want to disable the old services? (y/n) " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if systemctl is-enabled --quiet wxAsyncNewsGather.service 2>/dev/null; then
            sudo systemctl disable wxAsyncNewsGather.service
            echo "   ✅ Disabled wxAsyncNewsGather.service"
        fi
        
        if systemctl is-enabled --quiet wxNewsAPI.service 2>/dev/null; then
            sudo systemctl disable wxNewsAPI.service
            echo "   ✅ Disabled wxNewsAPI.service"
        fi
        
        echo ""
        echo "   Old services disabled. They won't start on boot."
    fi
fi

echo ""
echo "🎉 Setup complete! Your news system is now running with FastAPI."
