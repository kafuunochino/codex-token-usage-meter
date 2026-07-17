#!/usr/bin/env python3
"""Install the standalone macOS widget and optionally enable login launch."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


APP_NAME = "Token Usage Widget.app"
LAUNCH_AGENT_LABEL = "local.codex.token-usage-widget"


def run(command: list[str], *, check: bool = True) -> None:
    subprocess.run(command, check=check)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-autostart",
        action="store_true",
        help="install the app without launching it automatically at macOS login",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="do not open the widget after installation",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        raise SystemExit("The standalone widget currently supports macOS only.")

    plugin_root = Path(__file__).resolve().parents[1]
    installed_app = Path.home() / "Applications" / APP_NAME
    build_script = plugin_root / "widget" / "build_widget.sh"
    if not build_script.is_file():
        raise SystemExit(f"Widget build script not found: {build_script}")
    run([str(build_script)])
    if not installed_app.is_dir():
        raise SystemExit(f"Widget build did not create: {installed_app}")

    if not args.no_autostart:
        launch_agents = Path.home() / "Library" / "LaunchAgents"
        launch_agents.mkdir(parents=True, exist_ok=True)
        launch_agent = launch_agents / f"{LAUNCH_AGENT_LABEL}.plist"
        payload = {
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": ["/usr/bin/open", str(installed_app)],
            "RunAtLoad": True,
            "LimitLoadToSessionType": "Aqua",
            "ProcessType": "Interactive",
        }
        with launch_agent.open("wb") as handle:
            plistlib.dump(payload, handle)

        domain = f"gui/{os.getuid()}"
        subprocess.run(
            ["/bin/launchctl", "bootout", domain, str(launch_agent)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        run(["/bin/launchctl", "bootstrap", domain, str(launch_agent)])

    if not args.no_launch:
        run(["/usr/bin/open", str(installed_app)])

    print(f"Installed: {installed_app}")
    if not args.no_autostart:
        print("Login launch: enabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
