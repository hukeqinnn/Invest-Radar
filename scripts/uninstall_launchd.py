from __future__ import annotations

from pathlib import Path
import os
import subprocess


LABEL = "com.local.invest-radar"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def main() -> int:
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)], check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print(f"Uninstalled launchd job: {LABEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
