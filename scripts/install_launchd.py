from __future__ import annotations

from pathlib import Path
import os
import plistlib
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.local.invest-radar"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def main() -> int:
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    plist = {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "invest_radar",
            "run",
            "--config",
            str(PROJECT_ROOT / "config" / "sources.toml"),
        ],
        "WorkingDirectory": str(PROJECT_ROOT),
        "EnvironmentVariables": {
            "PYTHONPATH": str(PROJECT_ROOT),
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        "StartCalendarInterval": {
            "Hour": 10,
            "Minute": 30,
        },
        "StandardOutPath": str(logs_dir / "launchd.out.log"),
        "StandardErrorPath": str(logs_dir / "launchd.err.log"),
        "RunAtLoad": False,
    }

    with PLIST_PATH.open("wb") as fh:
        plistlib.dump(plist, fh, sort_keys=False)

    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)], check=False)
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)], check=True)
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{LABEL}"], check=True)

    print(f"Installed launchd job: {PLIST_PATH}")
    print("Schedule: every day at 10:30 local time")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
