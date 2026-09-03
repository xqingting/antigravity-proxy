#!/bin/bash
PORT="${1:-8765}"

# Kill by port
PIDS=$(lsof -ti ":${PORT}" 2>/dev/null)
if [ -n "$PIDS" ]; then
    kill -9 $PIDS 2>/dev/null
    echo '{"status": "stopped", "killed_pids": "'$PIDS'"}'
else
    echo '{"status": "not_running"}'
fi
