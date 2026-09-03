#!/usr/bin/env bash
# 停止 Antigravity 通用代理服务
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/.proxy.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "🛑 正在停止 Antigravity Proxy (PID: $PID)..."
        kill "$PID" 2>/dev/null || true
        sleep 1
        if ps -p "$PID" > /dev/null 2>&1; then
            kill -9 "$PID" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
        echo "✅ 服务已成功停止。"
        exit 0
    else
        echo "⚠️ 进程 $PID 已不在运行。"
        rm -f "$PID_FILE"
        exit 0
    fi
fi

# 备用方案：查找占用 8765 端口的 python 进程
PIDS=$(lsof -ti:8765 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "🛑 发现端口 8765 上的进程: $PIDS，正在终止..."
    kill -9 $PIDS 2>/dev/null || true
    echo "✅ 已释放端口 8765。"
else
    echo "ℹ️ 当前没有正在运行的代理服务。"
fi
