from __future__ import annotations

import getpass
import subprocess


SERVICE = "invest-radar-openai-api-key"
ACCOUNT = "openai"


def main() -> int:
    key = getpass.getpass("Paste OpenAI API key (input hidden): ").strip()
    if not key:
        print("No key entered.")
        return 1
    subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            ACCOUNT,
            "-s",
            SERVICE,
            "-w",
            key,
            "-U",
        ],
        check=True,
    )
    print(f"Saved API key to macOS Keychain: service={SERVICE}, account={ACCOUNT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
