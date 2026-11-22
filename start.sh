#!/usr/bin/env bash
# 启动 Antigravity 通用 OpenAI 兼容代理服务
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8765}"
MODEL="${2:-gemini-4-hydrogen}"
EFFORT="${3:-high}"
TIMEOUT="${4:-300}"

PID_FILE="$DIR/.proxy.pid"
LOG_FILE="$DIR/proxy.log"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️ Antigravity Proxy 已经在后台运行中 (PID: $PID)"
        echo "   地址: http://127.0.0.1:$PORT/v1"
        echo "   若要停止，请运行: ./stop.sh"
        exit 0
    fi
fi

echo "🚀 正在启动 Antigravity 通用代理服务 (端口: $PORT, 默认模型: $MODEL, 思考级别: $EFFORT, 超时: ${TIMEOUT}s)..."
nohup python3 "$DIR/agy_proxy.py" --port "$PORT" --model "$MODEL" --effort "$EFFORT" --timeout "$TIMEOUT" --max-concurrency 5 > "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 1

if ps -p "$NEW_PID" > /dev/null 2>&1; then
    echo "✅ 代理服务启动成功！"
    echo "   PID:      $NEW_PID"
    echo "   API 端点: http://127.0.0.1:$PORT/v1"
    echo "   默认模型: $MODEL"
    echo "   日志文件: $LOG_FILE"
    echo ""
    echo "💡 可通过运行 ./status.sh 查看健康状态，或运行 python3 test_client.py 测试调用。"
else
    echo "❌ 启动失败，请查看日志:"
    cat "$LOG_FILE"
    exit 1
fi
