#!/bin/bash
PORT="${1:-8765}"
MODEL="${2:-gemini-3.8-flash}"
EFFORT="${3:-high}"
MAX_CONCURRENCY="${4:-5}"

# Probe health first
if curl -s -m 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo '{"status": "already_running", "port": '$PORT'}'
    exit 0
fi

# Look for agy_proxy.py
SCRIPT_DIR=""
for candidate in \
    "$PWD/agy_proxy.py" \
    "$HOME/Desktop/通用项目/antigravity-proxy/agy_proxy.py" \
    "$(dirname "$0")/../../antigravity-proxy/agy_proxy.py"; do
    if [ -f "$candidate" ]; then
        SCRIPT_DIR="$(dirname "$candidate")"
        break
    fi
done

if [ -z "$SCRIPT_DIR" ]; then
    echo '{"status": "error", "message": "agy_proxy.py not found"}'
    exit 1
fi

nohup python3 "$SCRIPT_DIR/agy_proxy.py" --port "$PORT" --model "$MODEL" --effort "$EFFORT" --max-concurrency "$MAX_CONCURRENCY" > "$SCRIPT_DIR/proxy.log" 2>&1 &
PID=$!
echo "$PID" > "$SCRIPT_DIR/.proxy.pid"

sleep 1
if ps -p "$PID" > /dev/null 2>&1; then
    echo '{"status": "started", "pid": '$PID', "port": '$PORT'}'
else
    echo '{"status": "error", "message": "Failed to start proxy"}'
    exit 1
fi
