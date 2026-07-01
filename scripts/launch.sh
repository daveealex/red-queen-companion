#!/bin/bash
# Atlas Companion — Launch Script
# Starts the web server, then opens Chromium kiosk, then starts the orchestrator.
# Run from the ai-companion directory.

set -e

PROJECT_DIR="$HOME/ai-companion"
cd "$PROJECT_DIR"

GREEN='\033[0;32m'
NC='\033[0m'

log() { echo -e "${GREEN}[LAUNCH]${NC} $1"; }

log "Activating virtualenv..."
source venv/bin/activate

log "Starting web server on port 5000..."
python3 web/server.py &
WEB_PID=$!
sleep 2

# Verify server is up
if ! curl -s http://localhost:5000/api/status > /dev/null 2>&1; then
    err "Web server failed to start. Check logs above."
    kill $WEB_PID 2>/dev/null
    exit 1
fi
log "Web server running (PID $WEB_PID)"

log "Starting Chromium kiosk mode..."
chromium-browser --kiosk --no-first-run --disable-features=TranslateUI,Notifications http://localhost:5000 &
CHROMIUM_PID=$!
sleep 3
log "Chromium launched (PID $CHROMIUM_PID)"

log "Starting orchestrator..."
python3 orchestrator.py

# Cleanup
log "Shutting down..."
kill $WEB_PID $CHROMIUM_PID 2>/dev/null
wait 2>/dev/null
log "Goodbye!"
