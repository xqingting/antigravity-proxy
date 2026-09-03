#!/usr/bin/env bash
# 启动 Antigravity 状态栏热注入守护进程（后台运行）

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${DIR}/.metrics_injector.pid"
LOG_FILE="${DIR}/metrics_injector.log"

if [ -f "${PID_FILE}" ]; then
  PID=$(cat "${PID_FILE}")
  if ps -p "${PID}" > /dev/null 2>&1; then
    echo "ℹ️  统计栏守护进程已在运行中 (PID: ${PID})"
    exit 0
  fi
fi

echo "🚀 正在后台启动 Antigravity 状态栏热注入服务..."
nohup node "${DIR}/frontend-injector/live_inject.js" > "${LOG_FILE}" 2>&1 &
echo $! > "${PID_FILE}"

sleep 1
if ps -p $(cat "${PID_FILE}") > /dev/null 2>&1; then
  echo "✅ 启动成功！PID: $(cat "${PID_FILE}")"
  echo "   日志位置：${LOG_FILE}"
  echo "👉 现在打开或切换 Antigravity 任意对话，输入框底部均会自动显示实时统计！"
else
  echo "❌ 启动失败，请检查日志：${LOG_FILE}"
  exit 1
fi
