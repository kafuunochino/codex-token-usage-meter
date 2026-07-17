#!/usr/bin/env python3
"""Launch the native macOS floating token-usage widget."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("The floating widget currently supports macOS only.")

    script_dir = Path(__file__).resolve().parent
    plugin_root = Path(__file__).resolve().parents[3]
    installed_app = Path.home() / "Applications" / "Token Usage Widget.app"
    usage_script = script_dir / "token_usage.py"
    build_script = plugin_root / "widget" / "build_widget.sh"
    installed_binary = installed_app / "Contents" / "MacOS" / "TokenUsageWidget"
    source_files = [
        plugin_root / "widget" / "Widget.swift",
        plugin_root / "widget" / "Info.plist",
        usage_script,
        build_script,
    ]
    needs_update = not installed_binary.is_file()
    if not needs_update:
        installed_mtime = installed_binary.stat().st_mtime_ns
        needs_update = any(path.is_file() and path.stat().st_mtime_ns > installed_mtime for path in source_files)
    if needs_update:
        if not build_script.is_file():
            raise SystemExit(f"Widget build script not found: {build_script}")
        subprocess.run([str(build_script)], check=True)
    if not installed_app.is_dir():
        raise SystemExit(f"Widget app not found: {installed_app}")

    command = [
        "open",
        str(installed_app),
        "--args",
        "--script",
        str(usage_script),
        "--python",
        sys.executable,
    ]
    subprocess.run(command, check=True)
    print("Token Usage Widget launched. Drag to reposition; click × to close.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
