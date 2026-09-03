#!/usr/bin/env bash
set -e

# Antigravity Metrics Bar 一键补丁安装脚本
# 自动修改客户端 preload.js 挂载本地脚本，并完成 macOS 自签名

APP_PATH="/Applications/Antigravity.app"
RESOURCES_DIR="${APP_PATH}/Contents/Resources"
ASAR_FILE="${RESOURCES_DIR}/app.asar"
BACKUP_FILE="${RESOURCES_DIR}/app.asar.bak"
SCRIPT_SRC="/Users/wadeliu/Desktop/通用项目/antigravity-proxy/frontend-injector/antigravity-metrics-bar.js"
TEMP_DIR="/tmp/antigravity_asar_patch_$$"

echo "======================================================"
echo "🚀 开始安装 Antigravity 对话统计状态栏插件..."
echo "======================================================"

# 1. 检查客户端是否存在
if [ ! -d "${APP_PATH}" ]; then
  echo "❌ 未在 ${APP_PATH} 找到 Antigravity，请确认安装路径。"
  exit 1
fi

if [ ! -f "${SCRIPT_SRC}" ]; then
  echo "❌ 未找到源脚本：${SCRIPT_SRC}"
  exit 1
fi

# 2. 备份原文件
if [ ! -f "${BACKUP_FILE}" ]; then
  echo "📦 正在创建原始 app.asar 备份..."
  cp "${ASAR_FILE}" "${BACKUP_FILE}"
  echo "   已备份到：${BACKUP_FILE}"
else
  echo "ℹ️  已存在备份文件：${BACKUP_FILE}，跳过备份。"
fi

# 3. 准备临时解包目录
rm -rf "${TEMP_DIR}"
mkdir -p "${TEMP_DIR}"

echo "📂 正在解包 app.asar..."
npx --yes @electron/asar extract "${ASAR_FILE}" "${TEMP_DIR}"

PRELOAD_JS="${TEMP_DIR}/dist/preload.js"
if [ ! -f "${PRELOAD_JS}" ]; then
  echo "❌ 未在 asar 内部找到 dist/preload.js"
  rm -rf "${TEMP_DIR}"
  exit 1
fi

# 4. 检查是否已经植入过 Hook
if grep -q "Antigravity Metrics Bar Hook" "${PRELOAD_JS}"; then
  echo "ℹ️  dist/preload.js 已包含 Hook，重新刷新注入代码..."
  # 移除旧 hook
  sed -i '' '/\/\/ >>> Antigravity Metrics Bar Hook >>>/,/\/\/ <<< Antigravity Metrics Bar Hook <<</d' "${PRELOAD_JS}"
fi

echo "💉 注入脚本 Hook 到 dist/preload.js..."
cat << EOF >> "${PRELOAD_JS}"

// >>> Antigravity Metrics Bar Hook >>>
try {
  require('${SCRIPT_SRC}');
} catch (_err) {
  console.error('[Antigravity-Metrics] Hook load error:', _err);
}
// <<< Antigravity Metrics Bar Hook <<<
EOF

# 5. 重新打包 asar
echo "📦 正在重新打包 app.asar..."
npx --yes @electron/asar pack "${TEMP_DIR}" "${ASAR_FILE}" --unpack "{**/node_modules/chrome-devtools-mcp/**}"
rm -rf "${TEMP_DIR}"

# 6. 处理 macOS 签名与隔离属性
echo "🔐 正在修复 macOS 安全隔离属性与本地自签名..."
xattr -cr "${APP_PATH}" || true
codesign --force --deep --sign - "${APP_PATH}" || true

echo ""
echo "======================================================"
echo "🎉 恭喜！统计栏补丁已安装成功！"
echo "👉 请完全重启 Antigravity 客户端即可看到输入框底部的统计条。"
echo "👉 后续如果需要调整界面显示，直接修改："
echo "   ${SCRIPT_SRC}"
echo "   修改后刷新客户端即可立即生效，无需再次打包！"
echo "======================================================"
