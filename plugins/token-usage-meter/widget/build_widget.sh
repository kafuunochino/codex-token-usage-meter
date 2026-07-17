#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PLUGIN_DIR="${SCRIPT_DIR:h}"
APP_DIR="$PLUGIN_DIR/assets/TokenUsageWidget.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
USAGE_SCRIPT="$PLUGIN_DIR/skills/token-usage/scripts/token_usage.py"
MODULE_CACHE_DIR="$PLUGIN_DIR/.build/module-cache"

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$MODULE_CACHE_DIR"
cp "$SCRIPT_DIR/Info.plist" "$CONTENTS_DIR/Info.plist"
cp "$USAGE_SCRIPT" "$RESOURCES_DIR/token_usage.py"
chmod 644 "$RESOURCES_DIR/token_usage.py"
export CLANG_MODULE_CACHE_PATH="$MODULE_CACHE_DIR"
/usr/bin/swiftc \
  -O \
  -module-cache-path "$MODULE_CACHE_DIR" \
  -target "$(uname -m)-apple-macos13.0" \
  -framework AppKit \
  -framework Foundation \
  "$SCRIPT_DIR/TokenUsageWidget.swift" \
  -o "$MACOS_DIR/TokenUsageWidget"
chmod 755 "$MACOS_DIR/TokenUsageWidget"
/usr/bin/codesign --force --deep --sign - "$APP_DIR"
echo "$APP_DIR"
