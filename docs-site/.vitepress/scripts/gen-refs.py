#!/usr/bin/env python3
"""Orchestrator: run all reference generation scripts.

Usage:
    uv run python docs-site/.vitepress/scripts/gen-refs.py
"""

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SCRIPTS = [
    SCRIPTS_DIR / "gen-cli-ref.py",
    SCRIPTS_DIR / "gen-mcp-ref.py",
    SCRIPTS_DIR / "gen-api-ref.py",
]


def main():
    failed = False
    for script in SCRIPTS:
        print(f"\n{'=' * 60}")
        print(f"Running {script.name}")
        print("=" * 60)
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(SCRIPTS_DIR.parent.parent.parent),  # project root
        )
        if result.returncode != 0:
            print(f"FAILED: {script.name} (exit code {result.returncode})")
            failed = True

    if failed:
        print("\nSome scripts failed. Generated files may be incomplete.")
        sys.exit(1)
    else:
        print("\nAll reference docs generated successfully.")


if __name__ == "__main__":
    main()
