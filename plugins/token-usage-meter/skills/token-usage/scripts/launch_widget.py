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
    bundled_app = plugin_root / "assets" / "TokenUsageWidget.app"
    app_path = installed_app if installed_app.is_dir() else bundled_app
    usage_script = script_dir / "token_usage.py"
    if not app_path.is_dir():
        raise SystemExit(f"Widget app not found: {app_path}")

    command = [
        "open",
        str(app_path),
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
