#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PLUGIN_DIR="${SCRIPT_DIR:h}"
INSTALLED_APP_DIR="${HOME}/Applications/Token Usage Widget.app"
APP_DIR="${1:-$INSTALLED_APP_DIR}"
USAGE_SCRIPT="$PLUGIN_DIR/skills/token-usage/scripts/token_usage.py"
MODULE_CACHE_DIR="$PLUGIN_DIR/.build/module-cache"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/token-usage-widget.XXXXXX")"
STAGED_APP_DIR="$BUILD_ROOT/Token Usage Widget.app"
CONTENTS_DIR="$STAGED_APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

trap 'rm -rf "$BUILD_ROOT"' EXIT

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
  "$SCRIPT_DIR/Widget.swift" \
  -o "$MACOS_DIR/TokenUsageWidget"
chmod 755 "$MACOS_DIR/TokenUsageWidget"
/usr/bin/codesign --force --deep --sign - "$STAGED_APP_DIR"
mkdir -p "${APP_DIR:h}"
/usr/bin/ditto "$STAGED_APP_DIR" "$APP_DIR"
/usr/bin/codesign --verify --deep --strict "$APP_DIR"
echo "$APP_DIR"
