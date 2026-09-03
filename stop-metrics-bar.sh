#!/usr/bin/env bash
# 停止 Antigravity 状态栏热注入守护进程

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${DIR}/.metrics_injector.pid"

if [ ! -f "${PID_FILE}" ]; then
  echo "ℹ️  未找到运行中的统计栏服务。"
  exit 0
fi

PID=$(cat "${PID_FILE}")
if ps -p "${PID}" > /dev/null 2>&1; then
  echo "🛑 正在停止统计栏服务 (PID: ${PID})..."
  kill "${PID}" || true
  sleep 0.5
  rm -f "${PID_FILE}"
  echo "✅ 已成功停止！"
else
  echo "ℹ️  进程已不在运行。"
  rm -f "${PID_FILE}"
fi
