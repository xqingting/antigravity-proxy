#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="Antigravity Proxy"
DIST_DIR="$PROJ_ROOT/dist-app"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"

echo "🔨 [1/4] 编译原生 SwiftUI Release 二进制..."
cd "$SCRIPT_DIR"
swift build -c release

BIN_PATH="$SCRIPT_DIR/.build/release/AntigravityProxyApp"
if [ ! -f "$BIN_PATH" ]; then
  echo "❌ 未找到编译产物: $BIN_PATH"
  exit 1
fi

echo "📦 [2/4] 组装自包含 macOS App Bundle..."
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"

cp "$BIN_PATH" "$APP_BUNDLE/Contents/MacOS/AntigravityProxyApp"
chmod +x "$APP_BUNDLE/Contents/MacOS/AntigravityProxyApp"

# 内嵌代理核心与辅助脚本
cp "$PROJ_ROOT/agy_proxy.py" "$APP_BUNDLE/Contents/Resources/agy_proxy.py"
cp "$PROJ_ROOT/start.sh" "$APP_BUNDLE/Contents/Resources/start.sh"
cp "$PROJ_ROOT/stop.sh" "$APP_BUNDLE/Contents/Resources/stop.sh"
chmod +x \
  "$APP_BUNDLE/Contents/Resources/agy_proxy.py" \
  "$APP_BUNDLE/Contents/Resources/start.sh" \
  "$APP_BUNDLE/Contents/Resources/stop.sh"

# 复用应用图标
if [ -f "$PROJ_ROOT/src-tauri/icons/icon.icns" ]; then
  cp "$PROJ_ROOT/src-tauri/icons/icon.icns" "$APP_BUNDLE/Contents/Resources/icon.icns"
fi

echo "📝 [3/4] 生成 Info.plist (含本地网络权限声明)..."
cat > "$APP_BUNDLE/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>zh_CN</string>
    <key>CFBundleDisplayName</key>
    <string>Antigravity Proxy</string>
    <key>CFBundleExecutable</key>
    <string>AntigravityProxyApp</string>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
    <key>CFBundleIdentifier</key>
    <string>com.antigravity.proxy</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>Antigravity Proxy</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>2.0.0</string>
    <key>CFBundleVersion</key>
    <string>200</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSLocalNetworkUsageDescription</key>
    <string>Antigravity Proxy 需要本地网络权限以接收局域网客户端请求，并在授权情况下与局域网设备（如 NAS）协同通信。</string>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key>
        <true/>
        <key>NSAllowsArbitraryLoads</key>
        <true/>
    </dict>
</dict>
</plist>
EOF

echo "🔏 [4/4] 执行本地签名..."
codesign --force --deep --sign - "$APP_BUNDLE"

echo "✅ 原生 SwiftUI 应用构建成功: $APP_BUNDLE"
