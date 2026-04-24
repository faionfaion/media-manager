#!/bin/bash
# Local orchestrator: runs on nero-prod where pipelines live.
# Polls the remote media-manager API for pending commands and executes locally.
#
# Cron: */1 * * * * /home/nero/workspace/projects/media-manager-faion-net/scripts/local-orchestrator.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Load environment (bot tokens, API keys)
set -a
source "$HOME/workspace/.env" 2>/dev/null || true
set +a

LOCK="/tmp/media-manager-orchestrator.lock"
if [ -f "$LOCK" ]; then
    PID=$(cat "$LOCK" 2>/dev/null || true)
    if kill -0 "$PID" 2>/dev/null; then
        exit 0  # Already running
    fi
    rm -f "$LOCK"
fi
echo $$ > "$LOCK"
trap "rm -f $LOCK" EXIT

# Process local queue
python3 -c "
import sys; sys.path.insert(0, '.')
from app.security.auth import load_management_chats
from app.orchestrator.runner import process_queue
load_management_chats()
count = process_queue()
if count > 0:
    print(f'Processed {count} commands')
"

# Run scheduled tasks (check cron matches)
python3 -c "
import sys; sys.path.insert(0, '.')
from app.security.auth import load_management_chats
from app.orchestrator.runner import run_scheduled
load_management_chats()
run_scheduled()
"

# Morning briefing (once per day after 7 UTC)
python3 -c "
import sys; sys.path.insert(0, '.')
from app.security.auth import load_management_chats
from app.orchestrator.briefing import should_send_briefing, send_briefing
load_management_chats()
if should_send_briefing():
    send_briefing()
"

# Health monitoring + auto-healing (every 20 min via cron, cooldown per issue)
HEAL_MARKER="$PROJECT_DIR/logs/.last_heal"
HEAL_INTERVAL=1200  # 20 min in seconds
if [ ! -f "$HEAL_MARKER" ] || [ $(( $(date +%s) - $(stat -c %Y "$HEAL_MARKER" 2>/dev/null || echo 0) )) -ge $HEAL_INTERVAL ]; then
    touch "$HEAL_MARKER"
    python3 -c "
import sys; sys.path.insert(0, '.')
from app.security.auth import load_management_chats
from app.orchestrator.monitor import check_and_heal
load_management_chats()
check_and_heal()
"
fi
