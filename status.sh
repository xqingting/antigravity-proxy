#!/usr/bin/env bash
# 检查 Antigravity 代理服务运行状态
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8765}"

echo "🔍 检查 Antigravity 代理服务状态 (http://127.0.0.1:$PORT/health)..."
if curl -s -f "http://127.0.0.1:$PORT/health" > /tmp/agy_health.json 2>/dev/null; then
    echo "✅ 服务正常运行中！"
    cat /tmp/agy_health.json
    echo ""
else
    echo "❌ 服务未运行或端口 $PORT 无法访问。"
fi
