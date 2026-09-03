#!/usr/bin/env bash
set -e

# Antigravity Metrics Bar 一键卸载/还原脚本

APP_PATH="/Applications/Antigravity.app"
RESOURCES_DIR="${APP_PATH}/Contents/Resources"
ASAR_FILE="${RESOURCES_DIR}/app.asar"
BACKUP_FILE="${RESOURCES_DIR}/app.asar.bak"

echo "======================================================"
echo "🔄 开始还原 Antigravity 官方原始文件..."
echo "======================================================"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "❌ 未找到备份文件：${BACKUP_FILE}，无法自动还原。"
  exit 1
fi

echo "📦 正在使用备份恢复 app.asar..."
cp "${BACKUP_FILE}" "${ASAR_FILE}"

echo "🔐 重新签署官方应用..."
xattr -cr "${APP_PATH}" || true
codesign --force --deep --sign - "${APP_PATH}" || true

echo "✅ 已成功还原为官方纯净版！请重启 Antigravity。"
